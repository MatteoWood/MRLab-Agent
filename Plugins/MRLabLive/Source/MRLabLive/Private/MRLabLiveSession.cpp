#include "MRLabLiveSession.h"

#include "Async/Async.h"
#include "Containers/Queue.h"
#include "HAL/Event.h"
#include <atomic>
#include "AudioCapture.h"
#include "AudioDefines.h"
#include "Components/AudioComponent.h"
#include "Dom/JsonObject.h"
#include "HAL/FileManager.h"
#include "Misc/Base64.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Sound/SoundWaveProcedural.h"
#include "GuiToRawControlsUtils.h"
#include "NNEModelData.h"
#include "SpeechAnimationSolverV4.h"
#include "UObject/Package.h"

#include "Windows/AllowWindowsPlatformTypes.h"
#include <winhttp.h>
#include "Windows/HideWindowsPlatformTypes.h"

DEFINE_LOG_CATEGORY_STATIC(LogMRLabLive, Log, All);

namespace
{
	// Default audio format of the Live API: audio/pcm, 24 kHz, mono, 16 bit.
	constexpr int32 LiveSampleRate = 24000;

	// Lip sync: the solver looks this far ahead into the voice to animate the current moment (80 to 240 ms).
	constexpr int32 LookaheadMs = 80;
	// The voice is held back by the lookahead plus a margin for solving, so each frame is ready before its sound plays.
	constexpr int32 VoiceDelaySamples = (LookaheadMs + 40) * LiveSampleRate / 1000;
	// Mouth closing in silence: the Live API sends exact zeros between answers. A 20 ms step counts as voice above
	// this RMS level; the mouth controls fade in within about 60 ms before speech and out over about 200 ms after it.
	constexpr float VoiceRms = 0.003f;
	constexpr float MouthOpenPerStep = 0.35f;
	constexpr float MouthClosePerStep = 0.1f;

	/** All .md files in Saved/Knowledge (written by the editor's Update Knowledge button), one section per file. */
	FString LoadKnowledge()
	{
		const FString Dir = FPaths::ProjectSavedDir() / TEXT("Knowledge");
		TArray<FString> Files;
		IFileManager::Get().FindFilesRecursive(Files, *Dir, TEXT("*.md"), true, false);
		Files.Sort();

		FString Knowledge;
		for (const FString& File : Files)
		{
			FString Text;
			FFileHelper::LoadFileToString(Text, *File);
			FString Name = File;
			FPaths::MakePathRelativeTo(Name, *(Dir + TEXT("/")));
			Knowledge += FString::Printf(TEXT("\n\n--- Knowledge file: %s ---\n%s"), *Name, *Text);
		}

		if (Files.Num() == 0)
		{
			UE_LOG(LogMRLabLive, Warning, TEXT("No lab knowledge in %s; use Update Knowledge in the editor"), *FPaths::ConvertRelativePathToFull(Dir));
		}
		else
		{
			// Rough estimate (4 characters per token); the Live API allows up to 16384 instruction tokens.
			UE_LOG(LogMRLabLive, Log, TEXT("Lab knowledge: %d files, about %d tokens"), Files.Num(), Knowledge.Len() / 4);
		}
		return Knowledge;
	}
}

/**
 * WebSocket to the Live API over WinHttp. The engine's WebSocket client (libwebsockets) always sends
 * an Origin header, and the Live API refuses any handshake with an Origin header (403).
 * Connects and receives on a worker thread; callbacks run on the game thread; Send and Close are
 * called from the game thread.
 */
class FLiveSocket
{
public:
	TFunction<void()> OnOpened;
	TFunction<void(const FString&)> OnMessage;
	TFunction<void(const FString&)> OnClosed;

	~FLiveSocket()
	{
		Close();
	}

	void Open(const FString& Key)
	{
		Worker = Async(EAsyncExecution::Thread, [this, Key]() { Run(Key); });
	}

	void Send(const FString& Text)
	{
		FTCHARToUTF8 Utf8(*Text);
		if (Socket)
		{
			WinHttpWebSocketSend(Socket, WINHTTP_WEB_SOCKET_UTF8_MESSAGE_BUFFER_TYPE, (PVOID)Utf8.Get(), Utf8.Length());
		}
	}

	void Close()
	{
		// Callbacks already queued for the game thread are dropped; closing the handles cancels blocking calls.
	// Callbacks are posted as copies, so they may destroy this socket while they run.
		*bAlive = false;
		for (HINTERNET* Handle : { &Socket, &Request, &Connection, &Session })
		{
			if (*Handle)
			{
				WinHttpCloseHandle(*Handle);
				*Handle = nullptr;
			}
		}
		if (Worker.IsValid())
		{
			Worker.Wait();
		}
	}

private:
	void Post(TFunction<void()> Callback)
	{
		AsyncTask(ENamedThreads::GameThread, [bAlive = bAlive, Callback = MoveTemp(Callback)]()
		{
			if (*bAlive)
			{
				Callback();
			}
		});
	}

	void Run(const FString& Key)
	{
		const FString Header = TEXT("Authorization: Bearer ") + Key;
		DWORD Status = 0;
		DWORD StatusSize = sizeof(Status);
		Session = WinHttpOpen(TEXT("MRLabLive"), WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY, WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
		Connection = Session ? WinHttpConnect(Session, TEXT("api.openai.com"), INTERNET_DEFAULT_HTTPS_PORT, 0) : nullptr;
		Request = Connection ? WinHttpOpenRequest(Connection, TEXT("GET"), TEXT("/v1/live/sessions"), nullptr,
			WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE) : nullptr;
		if (!Request
			|| !WinHttpSetOption(Request, WINHTTP_OPTION_UPGRADE_TO_WEB_SOCKET, nullptr, 0)
			|| !WinHttpSendRequest(Request, *Header, DWORD(-1), WINHTTP_NO_REQUEST_DATA, 0, 0, 0)
			|| !WinHttpReceiveResponse(Request, nullptr)
			|| !WinHttpQueryHeaders(Request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER, WINHTTP_HEADER_NAME_BY_INDEX,
				&Status, &StatusSize, WINHTTP_NO_HEADER_INDEX)
			|| Status != 101
			|| !(Socket = WinHttpWebSocketCompleteUpgrade(Request, 0)))
		{
			const FString Error = FString::Printf(TEXT("connection failed (HTTP status %u, error %u)"), Status, GetLastError());
			Post([Callback = OnClosed, Error]() { Callback(Error); });
			return;
		}
		Post([Callback = OnOpened]() { Callback(); });

		TArray<uint8> Message;
		TArray<uint8> Chunk;
		Chunk.SetNumUninitialized(64 * 1024);
		while (true)
		{
			DWORD Read = 0;
			WINHTTP_WEB_SOCKET_BUFFER_TYPE Type;
			const DWORD Result = WinHttpWebSocketReceive(Socket, Chunk.GetData(), Chunk.Num(), &Read, &Type);
			if (Result != NO_ERROR)
			{
				const FString Error = FString::Printf(TEXT("receive failed (error %u)"), Result);
				Post([Callback = OnClosed, Error]() { Callback(Error); });
				return;
			}
			if (Type == WINHTTP_WEB_SOCKET_CLOSE_BUFFER_TYPE)
			{
				Post([Callback = OnClosed]() { Callback(TEXT("closed by server")); });
				return;
			}
			Message.Append(Chunk.GetData(), Read);
			if (Type == WINHTTP_WEB_SOCKET_UTF8_MESSAGE_BUFFER_TYPE)
			{
				FUTF8ToTCHAR Text(reinterpret_cast<const ANSICHAR*>(Message.GetData()), Message.Num());
				Post([Callback = OnMessage, Text = FString(Text.Length(), Text.Get())]() { Callback(Text); });
				Message.Reset();
			}
		}
	}

	HINTERNET Session = nullptr;
	HINTERNET Connection = nullptr;
	HINTERNET Request = nullptr;
	HINTERNET Socket = nullptr;
	TFuture<void> Worker;
	TSharedRef<bool> bAlive = MakeShared<bool>(true);
};

/**
 * Epic's real-time speech-to-face solver (StreamingADA, as used by MetaHuman's audio Live Link source).
 * Runs on its own thread, so solving never runs on the game thread. Frames is shared with the game
 * thread under Lock.
 */
struct FLipSync
{
	FLipSync(UNNEModelData* Model, const FString& Backend)
		: Solver(Model, Backend)
	{
		Resampler.Init(Audio::EResamplingMethod::FastSinc, 16000.f / LiveSampleRate, 1);
	}

	~FLipSync()
	{
		FPlatformProcess::ReturnSynchEventToPool(Wake);
	}

	void Start()
	{
		Worker = Async(EAsyncExecution::Thread, [this]()
		{
			while (!bStop)
			{
				Wake->Wait(100);
				TArray<float> Voice;
				while (!bStop && Input.Dequeue(Voice))
				{
					Process(Voice);
				}
			}
		});
	}

	void Stop()
	{
		bStop = true;
		Wake->Trigger();
		if (Worker.IsValid())
		{
			Worker.Wait();
		}
		if (SolveCount > 0)
		{
			UE_LOG(LogMRLabLive, Log, TEXT("Lip sync: %d frames solved, %.1f ms on average, %.1f ms at most, %d skipped because late"),
				SolveCount, SolveSeconds / SolveCount * 1000.0, SolveMaxSeconds * 1000.0, SkipCount);
		}
	}

	// Called from the game thread.
	void Add(TArray<float>&& Voice)
	{
		Input.Enqueue(MoveTemp(Voice));
		Wake->Trigger();
	}

	// Takes the next voice samples (24 kHz) and adds one frame of face controls per 20 ms.
	void Process(TArray<float>& Voice)
	{
		TArray<float> Resampled;
		Resampled.SetNumUninitialized(Voice.Num() * 2 / 3 + 16);
		int32 OutFrames = 0;
		Resampler.ProcessAudio(Voice.GetData(), Voice.Num(), false, Resampled.GetData(), Resampled.Num(), OutFrames);
		Pending.Append(Resampled.GetData(), OutFrames);

		int32 Used = 0;
		while (Pending.Num() - Used >= 320)
		{
			FSpeechAnimationAudioFrame In;
			In.AudioSamples = TArray<float>(Pending.GetData() + Used, 320);

			// Voice in the window from 40 ms before to the lookahead after the moment this step animates.
			float SumSquares = 0.f;
			for (const float Sample : In.AudioSamples)
			{
				SumSquares += Sample * Sample;
			}
			StepVoiced.Add(FMath::Sqrt(SumSquares / 320.f) > VoiceRms);
			if (StepVoiced.Num() > LookaheadMs / 20 + 3)
			{
				StepVoiced.RemoveAt(0);
			}
			MouthWeight = StepVoiced.Contains(true)
				? FMath::Min(1.f, MouthWeight + MouthOpenPerStep)
				: FMath::Max(0.f, MouthWeight - MouthClosePerStep);

			// The solver animates the moment one lookahead before the newest audio it has seen.
			const int64 Sample = (Solved + 320) * LiveSampleRate / 16000 - int64(LookaheadMs) * LiveSampleRate / 1000;
			Used += 320;
			Solved += 320;
			if (Sample < Playhead - LiveSampleRate / 5)
			{
				// Heard more than 0.2 s ago: the solver is far behind (busy GPU). Skip to catch up; the next solve restarts
				// its context. (Being a few ms late is normal: the mixer reads the voice a little ahead of what is audible.)
				bContiguous = false;
				++SkipCount;
				continue;
			}

			In.SamplesCount = 320;
			In.SampleRate = 16000;
			In.NumChannels = 1;
			In.bContiguous = bContiguous;
			In.Mood = EAudioDrivenAnimationMood::AutoDetect;
			In.Lookahead = LookaheadMs;
			bContiguous = true;

			FSpeechAnimationFrameData Out;
			const double SolveStart = FPlatformTime::Seconds();
			const bool bSolved = Solver.SolveAudioFrame(In, Out);
			const double SolveTime = FPlatformTime::Seconds() - SolveStart;
			SolveSeconds += SolveTime;
			SolveMaxSeconds = FMath::Max(SolveMaxSeconds, SolveTime);
			++SolveCount;
			if (!bSolved)
			{
				continue;
			}
			TMap<FString, float> Gui;
			for (int32 Index = 0; Index < Out.CurveNames.Num(); ++Index)
			{
				Gui.Add(Out.CurveNames[Index].ToString(), Out.CurveValues[Index]);
			}
			const TMap<FString, float> Raw = GuiToRawControlsUtils::ConvertGuiToRawControls(Gui);

			FScopeLock ScopeLock(&Lock);
			if (Names.IsEmpty())
			{
				for (const TPair<FString, float>& Pair : Raw)
				{
					Names.Add(FName(Pair.Key));
					bool bMouth = false;
					for (const TCHAR* Prefix : { TEXT("CTRL_expressions_jaw"), TEXT("CTRL_expressions_mouth"), TEXT("CTRL_expressions_tongue"), TEXT("CTRL_expressions_teeth") })
					{
						bMouth |= Pair.Key.StartsWith(Prefix);
					}
					IsMouth.Add(bMouth);
				}
			}
			TArray<float> Values;
			for (int32 Index = 0; Index < Names.Num(); ++Index)
			{
				// Mouth controls at 0 give the MetaHuman's closed neutral mouth.
				Values.Add(Raw.FindRef(Names[Index].ToString()) * (IsMouth[Index] ? MouthWeight : 1.f));
			}
			Frames.Emplace(Sample, MoveTemp(Values));
		}
		Pending.RemoveAt(0, Used);
	}

	FSpeechAnimationSolverV4 Solver;
	Audio::FResampler Resampler;
	TArray<float> Pending;     // 16 kHz samples not solved yet
	int64 Solved = 0;          // 16 kHz samples solved so far
	bool bContiguous = false;  // false resets the solver on the first frame
	TArray<bool> StepVoiced;   // voice in the latest 20 ms steps
	float MouthWeight = 0.f;   // 0 closes the mouth, 1 leaves the solver's mouth as it is
	TArray<bool> IsMouth;      // per control in Names
	std::atomic<int64> Playhead = 0; // voice sample being played, set by the game thread
	int32 SkipCount = 0;
	int32 SolveCount = 0;
	double SolveSeconds = 0.0;
	double SolveMaxSeconds = 0.0;

	TQueue<TArray<float>, EQueueMode::Spsc> Input;
	FEvent* Wake = FPlatformProcess::GetSynchEventFromPool(false);
	std::atomic<bool> bStop = false;
	TFuture<void> Worker;

	FCriticalSection Lock;
	TArray<FName> Names;                       // the 251 CTRL_expressions_* controls
	TArray<TPair<int64, TArray<float>>> Frames; // voice sample index (24 kHz), control values
};

UMRLabLiveSession::UMRLabLiveSession()
{
	PrimaryComponentTick.bCanEverTick = true;
	Instructions = TEXT(
		"You are a funny technician in the Mixed Reality Lab of TU Wien. "
		"You are helpful, witty and concise, and you speak like somebody who fixes "
		"strange machines between coffee breaks. Always answer in English. "
		"Answer questions about the lab from the lab knowledge below. If the knowledge does not cover "
		"a question, say so clearly and do not invent lab facts.");
}

void UMRLabLiveSession::StartSession()
{
	if (Socket.IsValid())
	{
		return;
	}

	const FString KeyPath = FPaths::ProjectSavedDir() / TEXT("OpenAIKey.txt");
	FString Key;
	FFileHelper::LoadFileToString(Key, *KeyPath);
	Key.TrimStartAndEndInline();
	if (Key.IsEmpty())
	{
		UE_LOG(LogMRLabLive, Error, TEXT("No OpenAI API key in %s"), *FPaths::ConvertRelativePathToFull(KeyPath));
		return;
	}

	const FString Knowledge = LoadKnowledge();
	const FString FullInstructions = Knowledge.IsEmpty() ? Instructions : Instructions + TEXT("\n\nLab knowledge:") + Knowledge;

	Socket = MakeShared<FLiveSocket>();
	TWeakObjectPtr<UMRLabLiveSession> WeakThis(this);
	Socket->OnOpened = [WeakThis, FullInstructions]()
	{
		UMRLabLiveSession* This = WeakThis.Get();
		if (!This)
		{
			return;
		}
		TSharedRef<FJsonObject> Format = MakeShared<FJsonObject>();
		Format->SetStringField(TEXT("type"), TEXT("audio/pcm"));
		Format->SetNumberField(TEXT("rate"), LiveSampleRate);
		TSharedRef<FJsonObject> Output = MakeShared<FJsonObject>();
		Output->SetStringField(TEXT("voice"), This->Voice);
		TSharedRef<FJsonObject> Audio = MakeShared<FJsonObject>();
		Audio->SetObjectField(TEXT("format"), Format);
		Audio->SetObjectField(TEXT("output"), Output);
		TSharedRef<FJsonObject> Session = MakeShared<FJsonObject>();
		Session->SetStringField(TEXT("model"), This->Model);
		Session->SetStringField(TEXT("instructions"), FullInstructions);
		Session->SetObjectField(TEXT("audio"), Audio);
		TSharedRef<FJsonObject> Event = MakeShared<FJsonObject>();
		Event->SetStringField(TEXT("type"), TEXT("session.start"));
		Event->SetObjectField(TEXT("session"), Session);
		This->Send(Event);
	};
	Socket->OnMessage = [WeakThis](const FString& Message)
	{
		if (UMRLabLiveSession* This = WeakThis.Get())
		{
			This->HandleMessage(Message);
		}
	};
	Socket->OnClosed = [WeakThis](const FString& Reason)
	{
		UE_LOG(LogMRLabLive, Warning, TEXT("Connection ended: %s"), *Reason);
		if (UMRLabLiveSession* This = WeakThis.Get())
		{
			This->Shutdown(Reason);
		}
	};
	Socket->Open(Key);
}

void UMRLabLiveSession::StopSession()
{
	if (Socket.IsValid() && bStarted)
	{
		TSharedRef<FJsonObject> Event = MakeShared<FJsonObject>();
		Event->SetStringField(TEXT("type"), TEXT("session.close"));
		Send(Event);
	}
	Shutdown(TEXT("stopped"));
}

void UMRLabLiveSession::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	StopSession();
	Super::EndPlay(EndPlayReason);
}

void UMRLabLiveSession::Send(const TSharedRef<FJsonObject>& Event)
{
	FString Text;
	FJsonSerializer::Serialize(Event, TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));
	Socket->Send(Text);
}

void UMRLabLiveSession::HandleMessage(const FString& Message)
{
	TSharedPtr<FJsonObject> Event;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Message), Event) || !Event.IsValid())
	{
		UE_LOG(LogMRLabLive, Warning, TEXT("Unreadable message: %s"), *Message.Left(300));
		return;
	}

	const FString Type = Event->GetStringField(TEXT("type"));
	if (Type == TEXT("session.output_audio.delta"))
	{
		TArray<uint8> Pcm;
		FBase64::Decode(Event->GetStringField(TEXT("delta")), Pcm);
		if (VoiceWave)
		{
			QueueVoice(reinterpret_cast<const int16*>(Pcm.GetData()), Pcm.Num() / sizeof(int16));
		}
	}
	else if (Type == TEXT("session.input_transcript.delta"))
	{
		AddTranscript(true, Event->GetStringField(TEXT("delta")));
	}
	else if (Type == TEXT("session.output_transcript.delta"))
	{
		AddTranscript(false, Event->GetStringField(TEXT("delta")));
	}
	else if (Type == TEXT("session.started"))
	{
		UE_LOG(LogMRLabLive, Log, TEXT("Session started: %s"), *Message.Left(300));
		bStarted = true;
		StartAudio();
	}
	else if (Type == TEXT("session.closed"))
	{
		UE_LOG(LogMRLabLive, Log, TEXT("Session closed: %s"), *Message.Left(500));
		Shutdown(Event->GetStringField(TEXT("reason")));
	}
	else if (Type == TEXT("error"))
	{
		UE_LOG(LogMRLabLive, Error, TEXT("Server error: %s"), *Message);
	}
	else
	{
		UE_LOG(LogMRLabLive, Log, TEXT("Event %s"), *Message.Left(300));
	}
}

void UMRLabLiveSession::QueueVoice(const int16* Samples, int32 NumSamples)
{
	TArray<int16> Pcm;
	if (VoiceWave->GetAvailableAudioByteCount() == 0)
	{
		// Start of the stream, or the voice ran dry: hold it back again by the lip sync delay.
		Pcm.AddZeroed(VoiceDelaySamples);
	}
	Pcm.Append(Samples, NumSamples);
	VoiceWave->QueueAudio(reinterpret_cast<const uint8*>(Pcm.GetData()), Pcm.Num() * sizeof(int16));
	VoiceQueued += Pcm.Num();

	if (LipSync.IsValid())
	{
		TArray<float> Floats;
		Floats.SetNumUninitialized(Pcm.Num());
		for (int32 Index = 0; Index < Pcm.Num(); ++Index)
		{
			Floats[Index] = Pcm[Index] / 32768.f;
		}
		LipSync->Add(MoveTemp(Floats));
	}
}

void UMRLabLiveSession::UpdateLipSync()
{
	if (!LipSync.IsValid() || !VoiceWave)
	{
		return;
	}
	// The voice sample being played now: everything queued minus what is still waiting in the wave.
	const int64 Playhead = VoiceQueued - VoiceWave->GetAvailableAudioByteCount() / sizeof(int16);
	LipSync->Playhead = Playhead;

	FScopeLock ScopeLock(&LipSync->Lock);
	TArray<TPair<int64, TArray<float>>>& Frames = LipSync->Frames;
	int32 Next = 0;
	while (Next < Frames.Num() && Frames[Next].Key <= Playhead)
	{
		++Next;
	}
	if (Next == 0)
	{
		return; // nothing solved up to the playhead yet
	}
	const TPair<int64, TArray<float>>& A = Frames[Next - 1];
	const TPair<int64, TArray<float>>* B = Next < Frames.Num() ? &Frames[Next] : nullptr;
	const float Alpha = B ? float(Playhead - A.Key) / float(B->Key - A.Key) : 0.f;
	for (int32 Index = 0; Index < LipSync->Names.Num(); ++Index)
	{
		LipSyncCurves.Add(LipSync->Names[Index], B ? FMath::Lerp(A.Value[Index], B->Value[Index], Alpha) : A.Value[Index]);
	}
	Frames.RemoveAt(0, Next - 1);
}

void UMRLabLiveSession::AddTranscript(bool bUser, const FString& Delta)
{
	FString& Text = bUser ? UserText : AgentText;
	if (bUser != bLastSpeakerUser)
	{
		// The other side spoke in between: log its finished utterance and start a new one for this side.
		const FString& Finished = bUser ? AgentText : UserText;
		if (!Finished.IsEmpty())
		{
			UE_LOG(LogMRLabLive, Log, TEXT("%s: %s"), bUser ? TEXT("Agent") : TEXT("User"), *Finished);
		}
		Text.Reset();
		bLastSpeakerUser = bUser;
	}
	Text += Delta;
	(bUser ? OnUserTranscript : OnAgentTranscript).Broadcast(Text);
}

void UMRLabLiveSession::StartAudio()
{
	Mic = NewObject<UAudioCapture>(this);
	if (!Mic->OpenDefaultAudioStream())
	{
		UE_LOG(LogMRLabLive, Error, TEXT("Could not open the default microphone"));
		StopSession();
		return;
	}
	MicChannels = Mic->GetNumChannels();
	MicRate = Mic->GetSampleRate();
	Resampler.Init(Audio::EResamplingMethod::FastSinc, float(LiveSampleRate) / MicRate, 1);
	MicHandle = Mic->AddGeneratorDelegate([this](const float* Samples, int32 NumSamples) { OnMicAudio(Samples, NumSamples); });
	Mic->StartCapturingAudio();
	UE_LOG(LogMRLabLive, Log, TEXT("Microphone open: %d Hz, %d channels"), MicRate, MicChannels);

	VoiceWave = NewObject<USoundWaveProcedural>(this);
	VoiceWave->SetSampleRate(LiveSampleRate);
	VoiceWave->NumChannels = 1;
	VoiceWave->Duration = INDEFINITELY_LOOPING_DURATION;
	VoiceWave->SoundGroup = SOUNDGROUP_Voice;
	VoiceWave->bLooping = false;
	VoiceQueued = 0;

	UNNEModelData* SolverModel = LoadObject<UNNEModelData>(GetTransientPackage(), *ISpeechAnimationSolver::GetLatestModelAssetPath());
	LipSyncModel = SolverModel;
	if (SolverModel)
	{
		// Epic's own backend switch for this solver (GPU NNERuntimeORTDml by default, or NNERuntimeORTCpu).
		const IConsoleVariable* BackendVar = IConsoleManager::Get().FindConsoleVariable(TEXT("mh.RealtimeAudio.Backend"));
		const FString Backend = BackendVar ? BackendVar->GetString() : TEXT("NNERuntimeORTDml");
		UE_LOG(LogMRLabLive, Log, TEXT("Lip sync backend: %s"), *Backend);
		LipSync = MakeShared<FLipSync>(SolverModel, Backend);
	}
	if (!LipSync.IsValid() || !LipSync->Solver.Initialize())
	{
		UE_LOG(LogMRLabLive, Error, TEXT("Lip sync solver could not start; the agent speaks without lip sync"));
		LipSync.Reset();
	}
	else
	{
		LipSync->Start();
	}

	Speaker = NewObject<UAudioComponent>(GetOwner());
	Speaker->bAutoActivate = false;
	Speaker->SetupAttachment(GetOwner()->GetRootComponent());
	Speaker->RegisterComponent();
	Speaker->SetSound(VoiceWave);
	Speaker->Play();
}

void UMRLabLiveSession::OnMicAudio(const float* Samples, int32 NumSamples)
{
	const int32 Frames = NumSamples / MicChannels;
	MicMono.SetNumUninitialized(Frames);
	for (int32 Frame = 0; Frame < Frames; ++Frame)
	{
		float Sum = 0.f;
		for (int32 Channel = 0; Channel < MicChannels; ++Channel)
		{
			Sum += Samples[Frame * MicChannels + Channel];
		}
		MicMono[Frame] = Sum / MicChannels;
	}

	MicResampled.SetNumUninitialized(Frames * LiveSampleRate / MicRate + 16);
	int32 OutFrames = 0;
	Resampler.ProcessAudio(MicMono.GetData(), Frames, false, MicResampled.GetData(), MicResampled.Num(), OutFrames);

	FScopeLock Lock(&MicLock);
	for (int32 Index = 0; Index < OutFrames; ++Index)
	{
		MicPcm.Add(int16(FMath::Clamp(MicResampled[Index] * 32767.f, -32768.f, 32767.f)));
	}
}

void UMRLabLiveSession::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	if (!bStarted)
	{
		return;
	}
	UpdateLipSync();

	TArray<int16> Pcm;
	{
		FScopeLock Lock(&MicLock);
		Pcm = MoveTemp(MicPcm);
		MicPcm.Reset();
	}
	if (Pcm.Num() > 0)
	{
		TSharedRef<FJsonObject> Event = MakeShared<FJsonObject>();
		Event->SetStringField(TEXT("type"), TEXT("session.input_audio.append"));
		Event->SetStringField(TEXT("audio"), FBase64::Encode(reinterpret_cast<const uint8*>(Pcm.GetData()), Pcm.Num() * sizeof(int16)));
		Send(Event);
	}
}

void UMRLabLiveSession::Shutdown(const FString& Reason)
{
	if (!Socket.IsValid())
	{
		return;
	}
	TSharedPtr<FLiveSocket> OldSocket = MoveTemp(Socket);
	Socket.Reset();
	bStarted = false;

	if (Mic)
	{
		Mic->RemoveGeneratorDelegate(MicHandle);
		Mic->StopCapturingAudio();
		Mic = nullptr;
	}
	if (Speaker)
	{
		Speaker->Stop();
		Speaker->DestroyComponent();
		Speaker = nullptr;
	}
	VoiceWave = nullptr;
	if (LipSync.IsValid())
	{
		LipSync->Stop();
		LipSync.Reset();
	}
	LipSyncModel = nullptr;
	LipSyncCurves.Reset();

	OldSocket->Close();
	OnSessionClosed.Broadcast(Reason);
}
