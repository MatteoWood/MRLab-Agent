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
#include "IPAddress.h"
#include "Sockets.h"
#include "SocketSubsystem.h"
#include "Misc/Base64.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Sound/SoundWaveProcedural.h"
#include "GuiToRawControlsUtils.h"
#include "NNE.h"
#include "NNEModelData.h"
#include "NNERuntimeCPU.h"
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
	// Catching up (D111, D112): with more than 0.3 s of voice waiting in the wave, silence is dropped down to 0.2 s
	// (the lip sync delay plus one 100 ms chunk of the stream).
	constexpr int32 CatchUpHighSamples = LiveSampleRate * 3 / 10;
	constexpr int32 CatchUpLevelSamples = LiveSampleRate * 2 / 10;
	constexpr int32 SilenceFrame = LiveSampleRate / 100; // 10 ms
	constexpr int32 SilenceKeptFrames = 10; // the first 100 ms of a silence never change
	// Stopping at a word end (D113): a word ends at 30 ms of quiet (below 0.2 of the loudest 10 ms since the cut, at
	// least below RMS 0.006); he says at most 0.5 s more. If the model talks on 4 s after the cut, he plays on from
	// its next word end.
	constexpr int32 WordEndQuietFrames = 3;
	constexpr int32 FinishMaxSamples = LiveSampleRate / 2;
	constexpr double DropMaxSeconds = 4.0;
	// Mouth closing in silence: the Live API sends exact zeros between answers. A 20 ms step counts as voice above
	// this RMS level; the mouth controls fade in within about 60 ms before speech and out over about 200 ms after it.
	constexpr float VoiceRms = 0.003f;
	constexpr float MouthOpenPerStep = 0.35f;
	constexpr float MouthClosePerStep = 0.1f;

	// Delegation cannot be switched off in the session config (omitted means client delegation), so it is ruled out
	// in the instructions, and any delegation that still happens is answered at once (see HandleMessage).
	const TCHAR* NoDelegationRule = TEXT(
		"Delegation policy: there is no backend and there are no tools. NEVER GENERATE <|SpawnThinking|>, "
		"CHECK, SEARCH, LOOK UP OR USE TOOLS. Answer right away from what you know. Facts about the lab come only from "
		"the lab knowledge below; if it does not contain them, say that you do not know. Never promise to look something up.");
	const TCHAR* DelegationReply = TEXT(
		"Nothing can be looked up here, there is no backend. Answer now from what you know: lab facts only from the lab "
		"knowledge in your instructions; if a lab fact is not there, say that you do not know.");

	// Frank's eyes (README 4.12): the camera service on the tracking PC keeps a short description of the people the
	// frontal camera sees and sends it to this PC as UDP packets (port in Saved/VisionPort.txt). The plugin adds each new
	// description to the session as silent context (session.thinking.append), so Frank answers questions about what he
	// sees at once, without delegating.
	// Views are added only while the visitor speaks: added at other times, they made the model speak on its own
	// (laptop test, 2026-11-09), and every turn must start with the visitor. Only views of pictures taken before the
	// visitor's latest words are added, so Frank sees what was there while the visitor spoke (fingers held up during
	// the question and lowered at its end stay up).
	const TCHAR* SeeingRule = TEXT(
		"What you see: a camera on top of your wall is your eyes, so you can see the visitors in front of you. Your view "
		"arrives silently, while the visitor speaks, as context that starts with \"View\" and a number. It describes each "
		"person you see, from your left to your right: where they stand, their clothes, what they hold, their pose and "
		"gesture now, and what they did in the last seconds. A person listed as \"Main visitor\" is the one your gaze "
		"follows, usually the one talking with you; the others are standing nearby. The newest view is what you see "
		"right now and replaces all "
		"earlier ones. It is always there, so you never need to look: never generate <|SpawnThinking|> for anything you "
		"see. A new view is never a reason to speak: you only ever reply to what the visitor says. When the visitor asks "
		"about anything visible (how they look, their clothes, what they hold or do, their pose or gestures, how many "
		"people are there, what you see), answer at once from the newest view, as if you saw it yourself. Never mention "
		"views, descriptions or a camera feed unless the visitor asks how you can see. Now and then you may add a short "
		"remark about something you see, such as something funny on their clothes, to your reply to what the visitor "
		"said, in character; never bring it up on your own, and do not describe the whole view unprompted. If the newest "
		"view says your eyes are not working, say that you cannot see right now.");
	const TCHAR* BlindView = TEXT("Your eyes are not working right now: you cannot see anything until a new view arrives.");
	constexpr double ViewSilenceSeconds = 3.0; // no packet for this long: the camera service is not running
	constexpr int32 ViewMaxAgeMs = 5000;       // an older camera frame means the camera stopped
	// The visitor counts as speaking until this long after the last word of their transcript.
	constexpr double UserTurnSeconds = 1.0;

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
 * Epic's real-time speech-to-face model (StreamingADA, as used by MetaHuman's audio Live Link source), run
 * the same way as FSpeechAnimationSolverV4 but on the CPU and with one difference: when a step is already
 * late, the model run is skipped while its audio still enters the model's 1 s input window, so the model
 * keeps its context (a restart makes it blink at once). On the GPU backend NNE runs DirectML on the
 * renderer's command queue, so each run waited behind the frames (up to 0.6 s under load, tested 2026-11-05).
 * Runs on its own thread. Frames is shared with the game thread under Lock.
 */
struct FLipSync
{
	explicit FLipSync(UNNEModelData* Model)
		: GuiNames(FSpeechAnimationSolverV4(Model, FString()).GetCurveNames())
	{
		Resampler.Init(Audio::EResamplingMethod::FastSinc, 16000.f / LiveSampleRate, 1);
		AudioBuffer.SetNumZeroed(16000);
		CurveValues.SetNumZeroed(81);
		MoodState.SetNumZeroed(50 * 21);
		BlinkBound.SetNumZeroed(3);
		BlinkBound[2] = FMath::RandRange(3.0, 5.0) * 50; // first blink after 3 to 5 s, in 50 Hz steps
		BlinkSel.SetNumZeroed(2);
		Step.SetNumZeroed(1);
		MoodInput.SetNumZeroed(21); // all zero = mood detected from the voice
		LookaheadInput.Add(LookaheadMs / 20);

		using namespace UE::NNE;
		const TWeakInterfacePtr<INNERuntimeCPU> Runtime = GetRuntime<INNERuntimeCPU>(TEXT("NNERuntimeORTCpu"));
		const TSharedPtr<IModelCPU> CPUModel = Runtime.IsValid() ? Runtime->CreateModelCPU(Model) : nullptr;
		ModelInstance = CPUModel ? CPUModel->CreateModelInstanceCPU() : nullptr;
		if (ModelInstance && ModelInstance->SetInputTensorShapes({ FTensorShape::Make({ 1, 16000 }), FTensorShape::Make({ 1, 81 }),
				FTensorShape::Make({ 1, 21 }), FTensorShape::Make({ 1, 50, 21 }), FTensorShape::Make({ 3 }), FTensorShape::Make({ 2 }),
				FTensorShape::Make({ 1 }), FTensorShape::Make({ 1 }) }) != EResultStatus::Ok)
		{
			ModelInstance.Reset();
		}
	}

	bool IsValid() const
	{
		return ModelInstance.IsValid();
	}

	// One model step: the newest 20 ms are already in AudioBuffer; updates CurveValues and the model state.
	bool RunModel()
	{
		using namespace UE::NNE;
		const TArray<FTensorBindingCPU> Inputs = {
			{ AudioBuffer.GetData(), uint64(AudioBuffer.Num() * sizeof(float)) },
			{ CurveValues.GetData(), uint64(CurveValues.Num() * sizeof(float)) },
			{ MoodInput.GetData(), uint64(MoodInput.Num() * sizeof(float)) },
			{ MoodState.GetData(), uint64(MoodState.Num() * sizeof(float)) },
			{ BlinkBound.GetData(), uint64(BlinkBound.Num() * sizeof(int64)) },
			{ BlinkSel.GetData(), uint64(BlinkSel.Num() * sizeof(int64)) },
			{ LookaheadInput.GetData(), uint64(LookaheadInput.Num() * sizeof(int64)) },
			{ Step.GetData(), uint64(Step.Num() * sizeof(int64)) } };
		const TArray<FTensorBindingCPU> Outputs = {
			{ CurveValues.GetData(), uint64(CurveValues.Num() * sizeof(float)) },
			{ MoodState.GetData(), uint64(MoodState.Num() * sizeof(float)) },
			{ BlinkBound.GetData(), uint64(BlinkBound.Num() * sizeof(int64)) },
			{ BlinkSel.GetData(), uint64(BlinkSel.Num() * sizeof(int64)) },
			{ Step.GetData(), uint64(Step.Num() * sizeof(int64)) } };
		return ModelInstance->RunSync(Inputs, Outputs) == EResultStatus::Ok;
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
				TPair<TArray<float>, int64> Item;
				while (!bStop && Input.Dequeue(Item))
				{
					Silence(Item.Value);
					Process(Item.Key);
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
			UE_LOG(LogMRLabLive, Log, TEXT("Lip sync: %d model runs, %.1f ms on average, %.1f ms at most, %d steps skipped because late"),
				SolveCount, SolveSeconds / SolveCount * 1000.0, SolveMaxSeconds * 1000.0, SkipCount);
		}
	}

	// Called from the game thread. HeardSilence: samples (24 kHz) of silence heard since the previous voice, because
	// the wave ran dry; they were never queued, so they do not count as solved voice.
	void Add(TArray<float>&& Voice, int64 HeardSilence)
	{
		Input.Enqueue(TPair<TArray<float>, int64>(MoveTemp(Voice), HeardSilence));
		Wake->Trigger();
	}

	// Silence that was heard between two pieces of voice: the model's input window and the mouth gate see it, so the
	// next frames do not animate the old words (e.g. the rest of an answer cut by the visitor, which was never heard).
	// The model runs are skipped (those moments are past); the model state stays, so no restart blink.
	void Silence(int64 Samples)
	{
		const int32 Num = int32(FMath::Min<int64>(Samples * 16000 / LiveSampleRate, 16000)) / 320 * 320;
		if (Num <= 0)
		{
			return;
		}
		FMemory::Memmove(AudioBuffer.GetData(), AudioBuffer.GetData() + Num, (16000 - Num) * sizeof(float));
		FMemory::Memzero(AudioBuffer.GetData() + 16000 - Num, Num * sizeof(float));
		for (int32 Steps = Num / 320; Steps > 0; --Steps)
		{
			StepVoiced.Add(false);
			if (StepVoiced.Num() > LookaheadMs / 20 + 3)
			{
				StepVoiced.RemoveAt(0);
			}
			MouthWeight = FMath::Max(0.f, MouthWeight - MouthClosePerStep);
		}
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
			// Slide the model's 1 s input window by 20 ms.
			const float* NewAudio = Pending.GetData() + Used;
			FMemory::Memmove(AudioBuffer.GetData(), AudioBuffer.GetData() + 320, (16000 - 320) * sizeof(float));
			FMemory::Memcpy(AudioBuffer.GetData() + 16000 - 320, NewAudio, 320 * sizeof(float));

			// Voice in the window from 40 ms before to the lookahead after the moment this step animates.
			float SumSquares = 0.f;
			for (int32 Index = 0; Index < 320; ++Index)
			{
				SumSquares += NewAudio[Index] * NewAudio[Index];
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
			if (Sample < Playhead)
			{
				// Already playing: skip the model run to catch up. The audio is in the window, so no context is lost.
				++SkipCount;
				continue;
			}

			{
				FScopeLock MoodScope(&MoodLock);
				if (PendingMood.Num() == MoodInput.Num())
				{
					MoodInput = MoveTemp(PendingMood);
					PendingMood.Reset();
				}
			}
			const double SolveStart = FPlatformTime::Seconds();
			const bool bSolved = RunModel();
			const double SolveTime = FPlatformTime::Seconds() - SolveStart;
			SolveSeconds += SolveTime;
			SolveMaxSeconds = FMath::Max(SolveMaxSeconds, SolveTime);
			++SolveCount;
			if (!bSolved)
			{
				continue;
			}
			TMap<FString, float> Gui;
			for (int32 Index = 0; Index < GuiNames.Num(); ++Index)
			{
				Gui.Add(GuiNames[Index].ToString(), CurveValues[Index]);
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
			Values.Add(MouthWeight); // last value: how much he is speaking (SpeakingWeight)
			Frames.Emplace(Sample, MoveTemp(Values));
		}
		Pending.RemoveAt(0, Used);
	}

	// Model and its inputs/state, as in FSpeechAnimationSolverV4.
	const TArray<FName> GuiNames;  // the model's 81 output controls
	TSharedPtr<UE::NNE::IModelInstanceCPU> ModelInstance;
	TArray<float> AudioBuffer;     // the last 1 s of voice, 16 kHz
	TArray<float> CurveValues;
	TArray<float> MoodState;
	TArray<int64> BlinkBound;
	TArray<int64> BlinkSel;
	TArray<int64> Step;
	TArray<float> MoodInput;
	TArray<int64> LookaheadInput;

	// Mood set from the game thread (SetLipSyncMood), taken over before the next model run.
	FCriticalSection MoodLock;
	TArray<float> PendingMood;

	Audio::FResampler Resampler;
	TArray<float> Pending;     // 16 kHz samples not stepped yet
	int64 Solved = 0;          // 16 kHz samples stepped so far
	TArray<bool> StepVoiced;  // voice in the latest 20 ms steps
	float MouthWeight = 0.f;   // 0 closes the mouth, 1 leaves the solver's mouth as it is
	TArray<bool> IsMouth;      // per control in Names
	std::atomic<int64> Playhead = 0; // voice sample being played, set by the game thread
	int32 SkipCount = 0;
	int32 SolveCount = 0;
	double SolveSeconds = 0.0;
	double SolveMaxSeconds = 0.0;

	TQueue<TPair<TArray<float>, int64>, EQueueMode::Spsc> Input; // voice, silence heard before it
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
	if (Socket.IsValid() || bReplaying)
	{
		return;
	}
	if (!ReplayFolder.IsEmpty())
	{
		StartReplay();
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
	// The session runs without a delegation backend: facts come from the instructions and the lab knowledge, the view
	// from the camera service (SeeingRule). Delegation wording for gpt-live-1 from OpenAI's GPT-Live prompting guide.
	const FString FullInstructions = Instructions + TEXT("\n\n") + NoDelegationRule + TEXT("\n\n") + SeeingRule
		+ (Knowledge.IsEmpty() ? FString() : TEXT("\n\nLab knowledge:") + Knowledge);

	// Decisions (README section 5, Step 9): triggers answer fixed questions on every transcript fragment of both sides.
	TArray<TSharedPtr<FJsonValue>> Triggers;
	DecisionItems.Reset();
	const FString DecisionsPath = FPaths::ProjectConfigDir() / TEXT("MRLabDecisions.json");
	FString DecisionsText;
	TSharedPtr<FJsonObject> Decisions;
	if (FFileHelper::LoadFileToString(DecisionsText, *DecisionsPath))
	{
		if (FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(DecisionsText), Decisions) && Decisions.IsValid())
		{
			Triggers = Decisions->GetArrayField(TEXT("triggers"));
			for (const TSharedPtr<FJsonValue>& Item : Decisions->GetArrayField(TEXT("items")))
			{
				DecisionItems.Add(Item->AsString());
			}
			UE_LOG(LogMRLabLive, Log, TEXT("Decisions: %d triggers, %d items from %s"), Triggers.Num(), DecisionItems.Num(), *DecisionsPath);
		}
		else
		{
			UE_LOG(LogMRLabLive, Error, TEXT("Decisions: %s is not valid JSON; no triggers"), *DecisionsPath);
		}
	}

	if (bRecordSession)
	{
		const FString Path = FPaths::ProjectSavedDir() / TEXT("Recordings") / FDateTime::Now().ToString(TEXT("%Y%m%d-%H%M%S")) / TEXT("events.jsonl");
		RecordFile.Reset(IFileManager::Get().CreateFileWriter(*Path));
		RecordStart = FPlatformTime::Seconds();
		UE_LOG(LogMRLabLive, Log, TEXT("Recording the session to %s"), *FPaths::ConvertRelativePathToFull(Path));
	}

	Socket = MakeShared<FLiveSocket>();
	TWeakObjectPtr<UMRLabLiveSession> WeakThis(this);
	Socket->OnOpened = [WeakThis, FullInstructions, Triggers]()
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
		if (Triggers.Num() > 0)
		{
			Session->SetArrayField(TEXT("triggers"), Triggers);
		}
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
	if (!Socket.IsValid())
	{
		return; // replay: nothing is sent
	}
	FString Text;
	FJsonSerializer::Serialize(Event, TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));
	Record(true, Text);
	Socket->Send(Text);
}

void UMRLabLiveSession::Record(bool bSent, const FString& Message)
{
	if (!RecordFile.IsValid())
	{
		return;
	}
	// JSON outside strings may contain line breaks; inside strings they are escaped, so replacing them keeps the JSON.
	FString OneLine = Message.Replace(TEXT("\r"), TEXT(" ")).Replace(TEXT("\n"), TEXT(" "));
	const FString Line = FString::Printf(TEXT("{\"t\":%.4f,\"d\":\"%s\",\"m\":%s}\n"),
		FPlatformTime::Seconds() - RecordStart, bSent ? TEXT("out") : TEXT("in"), *OneLine);
	const FTCHARToUTF8 Utf8(*Line);
	RecordFile->Serialize((void*)Utf8.Get(), Utf8.Length());
}

void UMRLabLiveSession::HandleMessage(const FString& Message)
{
	if (!bReplaying)
	{
		Record(false, Message);
	}
	TSharedPtr<FJsonObject> Event;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Message), Event) || !Event.IsValid())
	{
		UE_LOG(LogMRLabLive, Warning, TEXT("Unreadable message: %s"), *Message.Left(300));
		return;
	}

	const FString Type = Event->GetStringField(TEXT("type"));
	if (Type == TEXT("session.input_transcript.delta") || Type == TEXT("session.output_transcript.delta"))
	{
		FString EventId;
		const bool bUser = Type == TEXT("session.input_transcript.delta");
		int32 StartMs = -1;
		int32 EndMs = -1;
		Event->TryGetNumberField(TEXT("start_ms"), StartMs);
		Event->TryGetNumberField(TEXT("end_ms"), EndMs);
		if (Event->TryGetStringField(TEXT("event_id"), EventId))
		{
			Fragments.Add(EventId, { FPlatformTime::Seconds(), bUser, Event->GetStringField(TEXT("delta")), StartMs, EndMs });
		}
		// A new utterance of Frank (after the visitor's words, or after a pause with his voice run dry): anchor his voice
		// clock anew. Text runs about 1.4 s ahead of his audio, so a short gap inside an answer must not re-anchor.
		if (!bUser && StartMs >= 0)
		{
			const double Now = FPlatformTime::Seconds();
			if (AgentAnchorMs < 0 || bLastSpeakerUser
				|| (Now - LastAgentFragment > 2.0 && VoiceWave && VoiceWave->Waiting() == 0))
			{
				AgentAnchorMs = StartMs;
				AgentAnchorSample = -1;
			}
			if (bLastSpeakerUser && VoiceCut != EVoiceCut::None)
			{
				VoiceCut = EVoiceCut::None; // his answer to the visitor's words: it plays
				UE_LOG(LogMRLabLive, Log, TEXT("Voice plays again: a new answer, %.2f s after the cut"), Now - CutAt);
			}
			LastAgentFragment = Now;
			LastAgentEndMs = EndMs >= 0 ? EndMs : LastAgentEndMs;
		}
	}
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
		StartVoice();
		StartMicrophone();
		OpenViewSocket();
		for (int32 Index = 0; Index < DecisionItems.Num(); ++Index)
		{
			// Context for the decisions only; the voice model does not see it.
			TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>();
			Item->SetStringField(TEXT("type"), TEXT("message"));
			Item->SetStringField(TEXT("role"), TEXT("developer"));
			Item->SetStringField(TEXT("content"), DecisionItems[Index]);
			TSharedRef<FJsonObject> ItemEvent = MakeShared<FJsonObject>();
			ItemEvent->SetStringField(TEXT("type"), TEXT("decision.item.create"));
			ItemEvent->SetStringField(TEXT("event_id"), FString::Printf(TEXT("decision_item_%d"), Index));
			ItemEvent->SetObjectField(TEXT("item"), Item);
			Send(ItemEvent);
		}
	}
	else if (Type == TEXT("decision.event"))
	{
		HandleDecision(*Event, Message);
	}
	else if (Type == TEXT("session.closed"))
	{
		UE_LOG(LogMRLabLive, Log, TEXT("Session closed: %s"), *Message.Left(500));
		Shutdown(Event->GetStringField(TEXT("reason")));
	}
	else if (Type == TEXT("session.delegation.created"))
	{
		// No backend: answer the delegation at once so the model continues from its own instructions and knowledge.
		const TSharedPtr<FJsonObject>* Delegation = nullptr;
		if (Event->TryGetObjectField(TEXT("delegation"), Delegation))
		{
			UE_LOG(LogMRLabLive, Warning, TEXT("The model delegated (%s); answered that nothing can be looked up"), *Message.Left(300));
			TSharedRef<FJsonObject> Reply = MakeShared<FJsonObject>();
			Reply->SetStringField(TEXT("type"), TEXT("session.commentary.append"));
			Reply->SetStringField(TEXT("delegation_id"), (*Delegation)->GetStringField(TEXT("id")));
			Reply->SetStringField(TEXT("content"), DelegationReply);
			Send(Reply);
		}
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

void UMRLabLiveSession::HandleDecision(const FJsonObject& Event, const FString& Message)
{
	const TSharedPtr<FJsonObject>* Inner = nullptr;
	const TSharedPtr<FJsonObject>* Decision = nullptr;
	if (!Event.TryGetObjectField(TEXT("event"), Inner) || (*Inner)->GetStringField(TEXT("type")) != TEXT("decision.completed")
		|| !(*Inner)->TryGetObjectField(TEXT("decision"), Decision))
	{
		UE_LOG(LogMRLabLive, Warning, TEXT("Decision not completed: %s"), *Message.Left(1000));
		return;
	}

	// One line per decision: which side, how long after its fragment arrived, the fragment, the answers, the tokens.
	// The same answers parsed for the behaviour component (OnDecision).
	FString Answers;
	FMRLabDecision Parsed;
	for (const TSharedPtr<FJsonValue>& Value : (*Decision)->GetArrayField(TEXT("answers")))
	{
		const TSharedPtr<FJsonObject>& Answer = Value->AsObject();
		const FString AnswerType = Answer->GetStringField(TEXT("type"));
		FString Name;
		Answer->TryGetStringField(TEXT("name"), Name);
		FMRLabAnswer& Out = Parsed.Answers.AddDefaulted_GetRef();
		Out.Name = FName(Name);
		Answer->TryGetNumberField(TEXT("confidence"), Out.Confidence);
		if (AnswerType == TEXT("choice"))
		{
			FString Choice;
			if (!Answer->TryGetStringField(TEXT("choice"), Choice))
			{
				bool bChoice = false;
				Answer->TryGetBoolField(TEXT("choice"), bChoice);
				Choice = bChoice ? TEXT("true") : TEXT("false");
			}
			Out.Kind = FMRLabAnswer::EKind::Choice;
			Out.Choice = FName(Choice);
			const TArray<TSharedPtr<FJsonValue>>* Options = nullptr;
			if (Answer->TryGetArrayField(TEXT("probabilities"), Options))
			{
				for (const TSharedPtr<FJsonValue>& Option : *Options)
				{
					const TSharedPtr<FJsonObject>& OptionObject = Option->AsObject();
					FString OptionName;
					if (OptionObject.IsValid() && OptionObject->TryGetStringField(TEXT("value"), OptionName))
					{
						Out.Options.Add(FName(OptionName), float(OptionObject->GetNumberField(TEXT("probability"))));
					}
				}
			}
			Answers += FString::Printf(TEXT(" %s=%s(%.2f)"), *Name, *Choice, Answer->GetNumberField(TEXT("confidence")));
		}
		else if (AnswerType == TEXT("predicate"))
		{
			Out.Kind = FMRLabAnswer::EKind::Predicate;
			Out.Value = float(Answer->GetNumberField(TEXT("probability")));
			Answers += FString::Printf(TEXT(" %s=%.2f"), *Name, Answer->GetNumberField(TEXT("probability")));
		}
		else if (AnswerType == TEXT("score"))
		{
			Out.Kind = FMRLabAnswer::EKind::Score;
			Out.Value = float(Answer->GetNumberField(TEXT("score")));
			Answers += FString::Printf(TEXT(" %s=%.2f"), *Name, Answer->GetNumberField(TEXT("score")));
		}
		else
		{
			Parsed.Answers.Pop();
			Answers += FString::Printf(TEXT(" %s=%s"), *Name, *AnswerType);
		}
	}

	int64 InputTokens = 0;
	int64 CachedTokens = 0;
	const TSharedPtr<FJsonObject>* Usage = nullptr;
	if ((*Decision)->TryGetObjectField(TEXT("usage"), Usage))
	{
		InputTokens = int64((*Usage)->GetNumberField(TEXT("input_tokens")));
		const TSharedPtr<FJsonObject>* Details = nullptr;
		if ((*Usage)->TryGetObjectField(TEXT("input_tokens_details"), Details))
		{
			CachedTokens = int64((*Details)->GetNumberField(TEXT("cached_tokens")));
		}
	}
	++DecisionCount;
	DecisionInputTokens += InputTokens;
	DecisionCachedTokens += CachedTokens;

	FString SourceId;
	Event.TryGetStringField(TEXT("source_event_id"), SourceId);
	const FMRLabFragment* Fragment = Fragments.Find(SourceId);
	UE_LOG(LogMRLabLive, Log, TEXT("Decision %s %.2f s \"%s\":%s (tokens %lld, cached %lld)"),
		Fragment ? (Fragment->bUser ? TEXT("visitor") : TEXT("Frank")) : TEXT("?"),
		Fragment ? FPlatformTime::Seconds() - Fragment->Arrived : -1.0, Fragment ? *Fragment->Text : TEXT(""),
		*Answers, InputTokens, CachedTokens);

	if (Fragment)
	{
		Parsed.bVisitor = Fragment->bUser;
		Parsed.Text = Fragment->Text;
		Parsed.StartMs = Fragment->StartMs;
		Parsed.EndMs = Fragment->EndMs;
		Parsed.FragmentArrived = Fragment->Arrived;
		Parsed.Arrived = FPlatformTime::Seconds();
		OnDecision.Broadcast(Parsed);
	}
}

void UMRLabLiveSession::SetLipSyncMood(int32 Mood, float Intensity)
{
	if (!LipSync.IsValid())
	{
		return;
	}
	TArray<float> MoodArray;
	MoodArray.SetNumZeroed(21);
	if (Mood >= 0 && Mood < MoodArray.Num())
	{
		MoodArray[Mood] = Intensity; // as FSpeechAnimationSolverV4: the mood's slot holds its intensity, all zeros = detect
	}
	FScopeLock MoodScope(&LipSync->MoodLock);
	LipSync->PendingMood = MoveTemp(MoodArray);
	UE_LOG(LogMRLabLive, Verbose, TEXT("Lip sync mood %d, intensity %.2f"), Mood, Intensity);
}

void UMRLabLiveSession::QueueVoice(const int16* Samples, int32 NumSamples)
{
	if (AgentAnchorMs >= 0 && AgentAnchorSample < 0)
	{
		// The first audio of Frank's current utterance arrives now: its place in the voice is after everything queued.
		AgentAnchorSample = VoiceQueued + PendingVoice.Num();
	}
	PendingVoice.Append(Samples, NumSamples);
}

void UMRLabLiveSession::ReleaseVoice()
{
	if (!VoiceWave || PendingVoice.Num() == 0)
	{
		return;
	}
	if (VoiceCut == EVoiceCut::Dropping)
	{
		// The rest of the interrupted answer is left out. If the model still talks DropMaxSeconds after the cut (the
		// visitor's sound did not stop it), he plays on from its next word end.
		int32 From = PendingVoice.Num();
		if (FPlatformTime::Seconds() - CutAt > DropMaxSeconds)
		{
			for (int32 Frame = 0; Frame + SilenceFrame <= PendingVoice.Num(); Frame += SilenceFrame)
			{
				if (WordEnds(PendingVoice.GetData() + Frame, SilenceFrame))
				{
					From = Frame + SilenceFrame;
					VoiceCut = EVoiceCut::None;
					UE_LOG(LogMRLabLive, Log, TEXT("Voice plays again, %.1f s after the cut"), DropMaxSeconds);
					break;
				}
			}
		}
		PendingVoice.RemoveAt(0, From);
		if (PendingVoice.Num() == 0)
		{
			return;
		}
	}
	if (VoiceCut == EVoiceCut::Finishing)
	{
		// Play on to the end of the word, then leave out the rest.
		int32 Keep = 0;
		bool bEnded = false;
		while (Keep + SilenceFrame <= PendingVoice.Num() && !bEnded)
		{
			bEnded = WordEnds(PendingVoice.GetData() + Keep, SilenceFrame) || FinishLeft <= SilenceFrame;
			Keep += SilenceFrame;
			FinishLeft -= SilenceFrame;
		}
		if (!bEnded)
		{
			Keep = PendingVoice.Num();
		}
		else
		{
			for (int32 Index = 0; Index < SilenceFrame; ++Index)
			{
				int16& Sample = PendingVoice[Keep - SilenceFrame + Index];
				Sample = int16(Sample * (1.f - float(Index + 1) / SilenceFrame));
			}
			VoiceCut = EVoiceCut::Dropping;
			UE_LOG(LogMRLabLive, Log, TEXT("Voice stopped at a word end, %.2f s after the cut"), FPlatformTime::Seconds() - CutAt);
		}
		EnqueueVoice(PendingVoice.GetData(), Keep);
		PendingVoice.Reset();
		return;
	}
	// Catching up (D111, D112). The stream runs in real time: audio that piles up during a stall or a hitch (it comes
	// as a burst afterwards) would keep him late for the rest of the session. When more than CatchUpHighSamples would
	// wait in the wave, the stream's exact silence (zeros, in 10 ms frames, after the first 100 ms of a silence, so
	// the short zero runs inside speech never change) is dropped down to CatchUpLevelSamples. Nothing else waits.
	const int32 Count = PendingVoice.Num();
	const int32 Queued = VoiceWave->Waiting();
	int32 Drop = Queued + Count > CatchUpHighSamples ? Queued + Count - CatchUpLevelSamples : 0;
	const bool bDropping = Drop > 0;
	TArray<int16> Kept;
	Kept.Reserve(Count);
	int64 AnchorShift = 0; // silence dropped before the start of his current utterance
	for (int32 Frame = 0; Frame < Count; Frame += SilenceFrame)
	{
		const int32 N = FMath::Min(SilenceFrame, Count - Frame);
		bool bZero = N == SilenceFrame;
		for (int32 Index = Frame; bZero && Index < Frame + N; ++Index)
		{
			bZero = PendingVoice[Index] == 0;
		}
		SilentFrames = bZero ? SilentFrames + 1 : 0;
		if (SilentFrames > SilenceKeptFrames && Drop >= N)
		{
			Drop -= N;
			DroppedSilence += N;
			AnchorShift += VoiceQueued + Frame < AgentAnchorSample ? N : 0;
			continue;
		}
		Kept.Append(PendingVoice.GetData() + Frame, N);
	}
	AgentAnchorSample -= AnchorShift;
	if (!bDropping && DroppedSilence > 0)
	{
		if (DroppedSilence >= LiveSampleRate / 2)
		{
			UE_LOG(LogMRLabLive, Log, TEXT("Voice caught up: dropped %.2f s of silence"), DroppedSilence / float(LiveSampleRate));
		}
		DroppedSilence = 0;
	}
	if (Kept.Num() > 0)
	{
		EnqueueVoice(Kept.GetData(), Kept.Num());
	}
	PendingVoice.Reset();
}

void UMRLabLiveSession::EnqueueVoice(const int16* Samples, int32 NumSamples)
{
	TArray<int16> Pcm;
	const bool bDry = VoiceWave->Waiting() == 0;
	if (bDry)
	{
		// Start of the stream, or the voice ran dry: hold it back again by the lip sync delay.
		Pcm.AddZeroed(VoiceDelaySamples);
	}
	if (bDry && AgentAnchorSample >= VoiceQueued)
	{
		AgentAnchorSample += VoiceDelaySamples; // the start of his utterance is still to come: the delay goes in front
	}
	Pcm.Append(Samples, NumSamples);
	// Silence heard since the previous voice: the wave ran dry, and the part silenced after a word end (D113).
	const int64 HeardSilence = VoiceWave->TakeDrySamples() + SilencedSamples;
	SilencedSamples = 0;
	VoiceWave->Add(Pcm.GetData(), Pcm.Num());
	VoiceQueued += Pcm.Num();

	if (LipSync.IsValid())
	{
		TArray<float> Floats;
		Floats.SetNumUninitialized(Pcm.Num());
		for (int32 Index = 0; Index < Pcm.Num(); ++Index)
		{
			Floats[Index] = Pcm[Index] / 32768.f;
		}
		LipSync->Add(MoveTemp(Floats), HeardSilence);
	}
}

void UMRLabLiveSession::UpdateLipSync()
{
	if (!LipSync.IsValid() || !VoiceWave)
	{
		return;
	}
	// The voice sample being played now: everything queued minus what is still waiting in the wave.
	const int32 Waiting = VoiceWave->Waiting();
	const bool bDry = Waiting == 0;
	Playhead = VoiceQueued - Waiting;
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

	// Silenced after a word end (D113): the frames after it animate words that are never heard. The face of the
	// moment the word ended is held (and eased to rest below) until his voice goes on.
	const bool bInMute = Playhead >= MuteFrom && Playhead < MuteTo;
	if (bInMute && !bMuteHeld)
	{
		int32 First = 0;
		while (First + 1 < Frames.Num() && Frames[First + 1].Key <= MuteFrom)
		{
			++First;
		}
		const TPair<int64, TArray<float>>& HA = Frames[First];
		const TPair<int64, TArray<float>>* HB = First + 1 < Frames.Num() && HA.Key <= MuteFrom ? &Frames[First + 1] : nullptr;
		const float HAlpha = HB ? FMath::Clamp(float(MuteFrom - HA.Key) / float(HB->Key - HA.Key), 0.f, 1.f) : 0.f;
		MuteHold.Reset();
		for (int32 Index = 0; Index < LipSync->Names.Num(); ++Index)
		{
			MuteHold.Add(LipSync->Names[Index], HB ? FMath::Lerp(HA.Value[Index], HB->Value[Index], HAlpha) : HA.Value[Index]);
		}
		bMuteHeld = true;
	}
	else if (bMuteHeld && !bInMute && B && !bDry)
	{
		bMuteHeld = false; // new voice after the silenced part
	}
	if (bMuteHeld)
	{
		LipSyncCurves = MuteHold;
	}
	else
	{
		for (int32 Index = 0; Index < LipSync->Names.Num(); ++Index)
		{
			LipSyncCurves.Add(LipSync->Names[Index], B ? FMath::Lerp(A.Value[Index], B->Value[Index], Alpha) : A.Value[Index]);
		}
	}
	// The voice can stop without trailing silence (the stream pauses mid-word, or an interruption); then no newer frame
	// comes: the face eases back to rest within 0.25 s (mouth closed) instead of holding the last shape, and the
	// speaking weight falls. It comes back over 0.1 s once frames of new voice are there (inside the lip sync delay
	// put in front of it), never with the old frame: before, it jumped back at once, and the mouth opened in silence.
	const double Now = FPlatformTime::Seconds();
	const float Dt = LastLipSyncTime > 0.0 ? float(FMath::Min(Now - LastLipSyncTime, 0.25)) : 0.f;
	LastLipSyncTime = Now;
	if (bMuteHeld || (!B && bDry))
	{
		DryFade = FMath::Max(0.f, DryFade - Dt / 0.25f);
	}
	else if (B)
	{
		DryFade = FMath::Min(1.f, DryFade + Dt / 0.1f);
	}
	if (DryFade < 1.f)
	{
		const float Keep = FMath::SmoothStep(0.f, 1.f, DryFade);
		for (TPair<FName, float>& Control : LipSyncCurves)
		{
			Control.Value *= Keep;
		}
	}
	SpeakingWeight = bMuteHeld ? FMath::Max(0.f, SpeakingWeight - 0.1f)
		: B ? FMath::Lerp(A.Value.Last(), B->Value.Last(), Alpha) : (bDry ? FMath::Max(0.f, SpeakingWeight - 0.1f) : A.Value.Last());
	Frames.RemoveAt(0, Next - 1);
}

int64 UMRLabLiveSession::AgentFragmentSample(int32 StartMs) const
{
	if (StartMs < 0 || AgentAnchorMs < 0 || AgentAnchorSample < 0)
	{
		return -1;
	}
	return AgentAnchorSample + int64(StartMs - AgentAnchorMs) * LiveSampleRate / 1000;
}

float UMRLabLiveSession::FrankWordsLeft() const
{
	const int64 End = AgentFragmentSample(LastAgentEndMs);
	return End < 0 ? -1.f : float(End - Playhead) / LiveSampleRate;
}

bool UMRLabLiveSession::WordEnds(const int16* Frame, int32 Num)
{
	double Sum = 0.0;
	for (int32 Index = 0; Index < Num; ++Index)
	{
		const double Value = Frame[Index] / 32768.0;
		Sum += Value * Value;
	}
	const float Rms = float(FMath::Sqrt(Sum / FMath::Max(1, Num)));
	CutPeak = FMath::Max(CutPeak, Rms);
	CutQuietFrames = Rms < FMath::Max(0.006f, 0.2f * CutPeak) ? CutQuietFrames + 1 : 0;
	return CutQuietFrames >= WordEndQuietFrames;
}

void UMRLabLiveSession::StopAtWordEnd()
{
	if (!VoiceWave || VoiceCut != EVoiceCut::None)
	{
		return;
	}
	ReleaseVoice(); // what arrived this tick goes into the wave first
	CutAt = FPlatformTime::Seconds();
	CutPeak = 0.f;
	CutQuietFrames = 0;
	// The word may end in what waits in the wave: everything after its end there becomes silence.
	TArray<int16> Waiting;
	VoiceWave->CopyWaiting(Waiting);
	for (int32 Frame = 0; Frame + SilenceFrame <= Waiting.Num(); Frame += SilenceFrame)
	{
		if (WordEnds(Waiting.GetData() + Frame, SilenceFrame))
		{
			const int32 Keep = Frame + SilenceFrame;
			VoiceWave->SilenceFrom(Keep, SilenceFrame);
			MuteFrom = VoiceQueued - Waiting.Num() + Keep;
			MuteTo = VoiceQueued;
			SilencedSamples = MuteTo - MuteFrom; // heard as silence: the lip sync is told before the next voice
			VoiceCut = EVoiceCut::Dropping;
			UE_LOG(LogMRLabLive, Log, TEXT("Voice stopped at a word end, %.2f s after the cut"), Keep / float(LiveSampleRate));
			return;
		}
	}
	// Otherwise it ends in the audio still to come.
	VoiceCut = EVoiceCut::Finishing;
	FinishLeft = FinishMaxSamples;
}

void UMRLabVoiceWave::Add(const int16* Samples, int32 Num)
{
	FScopeLock ScopeLock(&Lock);
	if (Read > LiveSampleRate)
	{
		Buffer.RemoveAt(0, Read, EAllowShrinking::No);
		Read = 0;
	}
	Buffer.Append(Samples, Num);
}

int32 UMRLabVoiceWave::Waiting() const
{
	FScopeLock ScopeLock(&Lock);
	return Buffer.Num() - Read;
}

void UMRLabVoiceWave::CopyWaiting(TArray<int16>& Out) const
{
	FScopeLock ScopeLock(&Lock);
	Out = TArray<int16>(Buffer.GetData() + Read, Buffer.Num() - Read);
}

void UMRLabVoiceWave::SilenceFrom(int32 Offset, int32 Fade)
{
	FScopeLock ScopeLock(&Lock);
	const int32 Start = Read + FMath::Max(0, Offset - Fade);
	const int32 End = FMath::Min(Read + Offset, Buffer.Num());
	for (int32 Index = Start; Index < End; ++Index)
	{
		Buffer[Index] = int16(Buffer[Index] * (1.f - float(Index - Start + 1) / FMath::Max(1, End - Start)));
	}
	for (int32 Index = FMath::Max(End, Read); Index < Buffer.Num(); ++Index)
	{
		Buffer[Index] = 0;
	}
}

int32 UMRLabVoiceWave::OnGeneratePCMAudio(TArray<uint8>& OutAudio, int32 NumSamples)
{
	// Called on the audio render thread: what waits, then silence (as the engine does when a procedural wave runs dry).
	OutAudio.Reset();
	OutAudio.AddZeroed(NumSamples * sizeof(int16));
	FScopeLock ScopeLock(&Lock);
	const int32 Count = FMath::Min(NumSamples, Buffer.Num() - Read);
	if (Count > 0)
	{
		FMemory::Memcpy(OutAudio.GetData(), Buffer.GetData() + Read, Count * sizeof(int16));
		Read += Count;
	}
	DrySamples += NumSamples - FMath::Max(0, Count);
	return NumSamples;
}

int64 UMRLabVoiceWave::TakeDrySamples()
{
	FScopeLock ScopeLock(&Lock);
	const int64 Dry = DrySamples;
	DrySamples = 0;
	return Dry;
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
	if (bUser)
	{
		LastUserDelta = FPlatformTime::Seconds();
	}
	(bUser ? OnUserTranscript : OnAgentTranscript).Broadcast(Text);
}

void UMRLabLiveSession::OpenViewSocket()
{
	LastViewPacket = FPlatformTime::Seconds();
	const FString PortPath = FPaths::ProjectSavedDir() / TEXT("VisionPort.txt");
	FString PortText;
	FFileHelper::LoadFileToString(PortText, *PortPath);
	const int32 Port = FCString::Atoi(*PortText.TrimStartAndEnd());
	if (Port <= 0)
	{
		UE_LOG(LogMRLabLive, Warning, TEXT("No camera service port in %s; Frank cannot see"), *FPaths::ConvertRelativePathToFull(PortPath));
		return;
	}
	ISocketSubsystem* Subsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
	ViewSocket = Subsystem->CreateSocket(NAME_DGram, TEXT("MRLabLive camera views"), FNetworkProtocolTypes::IPv4);
	const TSharedRef<FInternetAddr> Address = Subsystem->CreateInternetAddr(FNetworkProtocolTypes::IPv4);
	Address->SetAnyAddress();
	Address->SetPort(Port);
	if (!ViewSocket || !ViewSocket->SetNonBlocking(true) || !ViewSocket->Bind(*Address))
	{
		UE_LOG(LogMRLabLive, Error, TEXT("Could not listen for the camera service on UDP port %d; Frank cannot see"), Port);
		CloseViewSocket();
		return;
	}
	UE_LOG(LogMRLabLive, Log, TEXT("Listening for the camera service on UDP port %d"), Port);
}

void UMRLabLiveSession::CloseViewSocket()
{
	if (ViewSocket)
	{
		ViewSocket->Close();
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(ViewSocket);
		ViewSocket = nullptr;
	}
}

void UMRLabLiveSession::ReceiveViews()
{
	const double Now = FPlatformTime::Seconds();
	TSharedPtr<FJsonObject> Packet; // only the newest packet counts
	if (ViewSocket)
	{
		static uint8 Buffer[65536];
		const TSharedRef<FInternetAddr> From = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->CreateInternetAddr();
		uint32 Pending = 0;
		int32 Read = 0;
		while (ViewSocket->HasPendingData(Pending) && ViewSocket->RecvFrom(Buffer, sizeof(Buffer), Read, *From))
		{
			const FUTF8ToTCHAR Text(reinterpret_cast<const ANSICHAR*>(Buffer), Read);
			TSharedPtr<FJsonObject> Parsed;
			if (FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(FString(Text.Length(), Text.Get())), Parsed) && Parsed.IsValid())
			{
				if (!bViewReceived)
				{
					UE_LOG(LogMRLabLive, Log, TEXT("Camera service: first view from %s"), *From->ToString(false));
					bViewReceived = true;
				}
				Packet = Parsed;
				LastViewPacket = Now;
			}
		}
	}
	if (!Packet.IsValid())
	{
		if (Now - LastViewPacket > ViewSilenceSeconds)
		{
			SetBlind(ViewSocket ? TEXT("no view from the camera service for 3 s") : TEXT("not listening for the camera service"));
		}
		return;
	}
	const int32 AgeMs = int32(Packet->GetNumberField(TEXT("age_ms")));
	if (AgeMs > ViewMaxAgeMs)
	{
		SetBlind(FString::Printf(TEXT("the newest camera frame is %d ms old"), AgeMs));
		return;
	}
	if (bBlind)
	{
		UE_LOG(LogMRLabLive, Log, TEXT("Camera service: views arriving"));
	}
	bBlind = false;
	// Added to the session while the visitor speaks (TickComponent).
	NewestView = Packet->GetStringField(TEXT("description"));
	NewestViewTaken = Now - Packet->GetNumberField(TEXT("frame_age_ms")) / 1000.0;
}

void UMRLabLiveSession::SetBlind(const FString& Reason)
{
	if (!bBlind)
	{
		UE_LOG(LogMRLabLive, Warning, TEXT("Camera service: %s; Frank will be told that he cannot see"), *Reason);
	}
	bBlind = true;
	NewestView = BlindView;
	NewestViewTaken = 0.0; // always counts as before the visitor's words
}

void UMRLabLiveSession::AppendView(const FString& Text)
{
	++ViewCount;
	TSharedRef<FJsonObject> Event = MakeShared<FJsonObject>();
	Event->SetStringField(TEXT("type"), TEXT("session.thinking.append"));
	Event->SetField(TEXT("delegation_id"), MakeShared<FJsonValueNull>()); // null: general session context
	Event->SetStringField(TEXT("content"), FString::Printf(TEXT("View %d: %s"), ViewCount, *Text));
	Send(Event);
}

void UMRLabLiveSession::StartMicrophone()
{
	if (!TestInputWav.IsEmpty())
	{
		// Test input: a WAV file (24 kHz, mono, 16 bit PCM) stands in for the visitor, sent in real time.
		TArray<uint8> Bytes;
		FFileHelper::LoadFileToArray(Bytes, *TestInputWav);
		int32 Pos = 12;
		int32 Channels = 0;
		int32 Rate = 0;
		int32 Bits = 0;
		while (Bytes.Num() >= 12 && Pos + 8 <= Bytes.Num())
		{
			const int32 Size = *reinterpret_cast<const int32*>(Bytes.GetData() + Pos + 4);
			if (FMemory::Memcmp(Bytes.GetData() + Pos, "fmt ", 4) == 0 && Pos + 24 <= Bytes.Num())
			{
				Channels = *reinterpret_cast<const int16*>(Bytes.GetData() + Pos + 10);
				Rate = *reinterpret_cast<const int32*>(Bytes.GetData() + Pos + 12);
				Bits = *reinterpret_cast<const int16*>(Bytes.GetData() + Pos + 22);
			}
			else if (FMemory::Memcmp(Bytes.GetData() + Pos, "data", 4) == 0)
			{
				const int32 Available = FMath::Min(Size, Bytes.Num() - Pos - 8);
				TestPcm.SetNumUninitialized(Available / 2);
				FMemory::Memcpy(TestPcm.GetData(), Bytes.GetData() + Pos + 8, TestPcm.Num() * 2);
				break;
			}
			Pos += 8 + Size + (Size & 1);
		}
		if (Channels != 1 || Rate != LiveSampleRate || Bits != 16 || TestPcm.Num() == 0)
		{
			UE_LOG(LogMRLabLive, Error, TEXT("Test input %s is not a 24 kHz mono 16 bit WAV (%d Hz, %d channels, %d bit)"), *TestInputWav, Rate, Channels, Bits);
			TestPcm.Reset();
			StopSession();
			return;
		}
		bTestInput = true;
		TestSent = 0;
		TestStart = FPlatformTime::Seconds();
		UE_LOG(LogMRLabLive, Log, TEXT("Test input instead of the microphone: %s, %.1f s"), *TestInputWav, TestPcm.Num() / float(LiveSampleRate));
		return;
	}

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
}

namespace
{
	float PcmRms(const int16* Pcm, int32 Num)
	{
		double Sum = 0.0;
		for (int32 Index = 0; Index < Num; ++Index)
		{
			const double Value = Pcm[Index] / 32768.0;
			Sum += Value * Value;
		}
		return Num > 0 ? float(FMath::Sqrt(Sum / Num)) : 0.f;
	}
}

void UMRLabLiveSession::StartReplay()
{
	const FString Path = ReplayFolder / TEXT("events.jsonl");
	TArray<FString> Lines;
	if (!FFileHelper::LoadFileToStringArray(Lines, *Path))
	{
		UE_LOG(LogMRLabLive, Error, TEXT("Replay: cannot read %s"), *Path);
		return;
	}
	ReplayEvents.Reset();
	ReplayLevels.Reset();
	for (const FString& Line : Lines)
	{
		TSharedPtr<FJsonObject> Entry;
		if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Line), Entry) || !Entry.IsValid())
		{
			continue;
		}
		const TSharedPtr<FJsonObject> Message = Entry->GetObjectField(TEXT("m"));
		if (Entry->GetStringField(TEXT("d")) != TEXT("in"))
		{
			// The visitor audio that was sent: only its loudness is replayed (VisitorLevel).
			if (Message->GetStringField(TEXT("type")) == TEXT("session.input_audio.append"))
			{
				TArray<uint8> Bytes;
				FBase64::Decode(Message->GetStringField(TEXT("audio")), Bytes);
				ReplayLevels.Emplace(Entry->GetNumberField(TEXT("t")), PcmRms(reinterpret_cast<const int16*>(Bytes.GetData()), Bytes.Num() / 2));
			}
			continue;
		}
		if (Message->GetStringField(TEXT("type")) == TEXT("session.started"))
		{
			continue; // would open the microphone and the camera socket
		}
		FString Text;
		FJsonSerializer::Serialize(Message.ToSharedRef(), TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Text));
		ReplayEvents.Emplace(Entry->GetNumberField(TEXT("t")), MoveTemp(Text));
	}
	UE_LOG(LogMRLabLive, Log, TEXT("Replay of %s: %d messages, %.1f s"), *Path, ReplayEvents.Num(),
		ReplayEvents.Num() > 0 ? ReplayEvents.Last().Key : 0.0);
	bReplaying = true;
	bStarted = true;
	ReplayNext = 0;
	ReplayLevelNext = 0;
	ReplayStart = FPlatformTime::Seconds();
	StartVoice();
}

void UMRLabLiveSession::StartVoice()
{
	VoiceWave = NewObject<UMRLabVoiceWave>(this);
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
		LipSync = MakeShared<FLipSync>(SolverModel);
	}
	if (!LipSync.IsValid() || !LipSync->IsValid())
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
	if (bReplaying)
	{
		const double Elapsed = FPlatformTime::Seconds() - ReplayStart;
		while (ReplayNext < ReplayEvents.Num() && ReplayEvents[ReplayNext].Key <= Elapsed)
		{
			HandleMessage(ReplayEvents[ReplayNext++].Value);
		}
		while (ReplayLevelNext < ReplayLevels.Num() && ReplayLevels[ReplayLevelNext].Key <= Elapsed)
		{
			VisitorLevel = ReplayLevels[ReplayLevelNext++].Value;
		}
		ReleaseVoice();
		UpdateLipSync();
		if (ReplayNext >= ReplayEvents.Num() && (ReplayEvents.Num() == 0 || Elapsed > ReplayEvents.Last().Key + 2.0))
		{
			Shutdown(TEXT("replay finished"));
		}
		return;
	}
	ReleaseVoice();
	UpdateLipSync();

	ReceiveViews();
	const double Now = FPlatformTime::Seconds();
	if (bLastSpeakerUser && Now - LastUserDelta < UserTurnSeconds && NewestViewTaken <= LastUserDelta
		&& !NewestView.IsEmpty() && NewestView != LastView)
	{
		LastView = NewestView;
		AppendView(NewestView);
		UE_LOG(LogMRLabLive, Log, TEXT("View %d: %s"), ViewCount, *NewestView);
	}

	TArray<int16> Pcm;
	if (bTestInput)
	{
		// The file in real time, then silence (the microphone also sends all the time).
		const int64 Due = int64((Now - TestStart) * LiveSampleRate);
		for (; TestSent < Due; ++TestSent)
		{
			Pcm.Add(TestSent < TestPcm.Num() ? TestPcm[TestSent] : 0);
		}
	}
	else
	{
		FScopeLock Lock(&MicLock);
		Pcm = MoveTemp(MicPcm);
		MicPcm.Reset();
	}
	if (Pcm.Num() > 0)
	{
		VisitorLevel = PcmRms(Pcm.GetData(), Pcm.Num());
		TSharedRef<FJsonObject> Event = MakeShared<FJsonObject>();
		Event->SetStringField(TEXT("type"), TEXT("session.input_audio.append"));
		Event->SetStringField(TEXT("audio"), FBase64::Encode(reinterpret_cast<const uint8*>(Pcm.GetData()), Pcm.Num() * sizeof(int16)));
		Send(Event);
	}
}

void UMRLabLiveSession::Shutdown(const FString& Reason)
{
	if (!Socket.IsValid() && !bReplaying)
	{
		return;
	}
	TSharedPtr<FLiveSocket> OldSocket = MoveTemp(Socket);
	Socket.Reset();
	bStarted = false;
	bReplaying = false;
	ReplayEvents.Reset();
	ReplayLevels.Reset();
	VisitorLevel = 0.f;
	PendingVoice.Reset();
	DroppedSilence = 0;
	LastAgentEndMs = -1;
	VoiceCut = EVoiceCut::None;
	MuteFrom = MuteTo = 0;
	SilencedSamples = 0;
	bMuteHeld = false;
	SilentFrames = 0;
	bTestInput = false;
	TestPcm.Reset();
	if (DecisionCount > 0)
	{
		UE_LOG(LogMRLabLive, Log, TEXT("Decisions: %d, input tokens %lld (cached %lld)"), DecisionCount, DecisionInputTokens, DecisionCachedTokens);
	}
	DecisionCount = 0;
	DecisionInputTokens = 0;
	DecisionCachedTokens = 0;
	Fragments.Reset();
	RecordFile.Reset(); // closes the file
	// A new session starts without context: the next one gets the current view again.
	CloseViewSocket();
	bViewReceived = false;
	NewestView.Reset();
	NewestViewTaken = 0.0;
	LastView.Reset();
	ViewCount = 0;
	bBlind = false;

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
	SpeakingWeight = 0.f;
	Playhead = 0;
	AgentAnchorMs = -1;
	AgentAnchorSample = -1;
	LastAgentFragment = 0.0;

	if (OldSocket.IsValid())
	{
		OldSocket->Close();
	}
	OnSessionClosed.Broadcast(Reason);
}
