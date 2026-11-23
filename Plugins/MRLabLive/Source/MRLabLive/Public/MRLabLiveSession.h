#pragma once

#include "CoreMinimal.h"
#include "AudioResampler.h"
#include "Components/ActorComponent.h"
#include "Generators/AudioGenerator.h"
#include "Sound/SoundWaveProcedural.h"
#include "MRLabLiveSession.generated.h"

class FLiveSocket;
struct FLipSync;
class FJsonObject;
class UAudioCapture;
class UAudioComponent;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FMRLabLiveText, const FString&, Text);

/** A transcript fragment as it arrived, kept to time the decisions made on it. */
struct FMRLabFragment
{
	double Arrived = 0.0;
	bool bUser = false;
	FString Text;
	int32 StartMs = -1; // the fragment's start_ms / end_ms on the session timeline
	int32 EndMs = -1;
};

/** One answer of a Decisions trigger: a choice (probability of every option), a predicate or a score. */
struct FMRLabAnswer
{
	enum class EKind : uint8 { Choice, Predicate, Score };
	FName Name;
	EKind Kind = EKind::Choice;
	FName Choice;               // the chosen option (choice)
	TMap<FName, float> Options; // probability of each option (choice)
	float Confidence = 0.f;     // choice and score
	float Value = 0.f;          // probability (predicate) or score 0..1 (score)

	/** Probability of an option (choice), 0 if it is not listed. */
	float Probability(FName Option) const { return Options.FindRef(Option); }
};

/** A completed decision on one transcript fragment, with the fragment it was made on. */
struct FMRLabDecision
{
	bool bVisitor = false;        // made on the visitor's words (else on Frank's)
	FString Text;                 // the fragment
	int32 StartMs = -1;           // the fragment's start_ms / end_ms (-1 if unknown)
	int32 EndMs = -1;
	double FragmentArrived = 0.0; // FPlatformTime::Seconds() when the fragment arrived (0 if unknown)
	double Arrived = 0.0;         // when the decision arrived
	TArray<FMRLabAnswer> Answers;

	const FMRLabAnswer* Find(FName Name) const { return Answers.FindByPredicate([Name](const FMRLabAnswer& A) { return A.Name == Name; }); }
};

DECLARE_MULTICAST_DELEGATE_OneParam(FMRLabOnDecision, const FMRLabDecision&);

/** Frank's voice: a procedural sound wave that plays from its own buffer, so audio waiting to be heard can still be
 * silenced (the visitor talks over him, D113). Add and the queries run on the game thread, the audio on the audio
 * render thread. */
UCLASS()
class UMRLabVoiceWave : public USoundWaveProcedural
{
	GENERATED_BODY()

public:
	UMRLabVoiceWave(const FObjectInitializer& ObjectInitializer) : Super(ObjectInitializer) {}

	void Add(const int16* Samples, int32 Num);
	/** Samples waiting to be heard. */
	int32 Waiting() const;
	void CopyWaiting(TArray<int16>& Out) const;
	/** RMS (0 to 1) of Count waiting samples from Offset on (0 where nothing waits). */
	float WaitingRms(int32 Offset, int32 Count) const;
	/** What waits from Offset on becomes silence; the Fade samples before Offset fade out. */
	void SilenceFrom(int32 Offset, int32 Fade);
	/** Samples of silence played because nothing was waiting, since the previous call. */
	int64 TakeDrySamples();

	virtual int32 OnGeneratePCMAudio(TArray<uint8>& OutAudio, int32 NumSamples) override;

private:
	mutable FCriticalSection Lock;
	TArray<int16> Buffer;
	int32 Read = 0; // samples of Buffer already heard
	int64 DrySamples = 0;
};

/**
 * Spoken conversation with OpenAI gpt-live-1.1 through the Live API (WebSocket over WinHttp, Windows only).
 * Streams the default microphone to the model and plays the agent's voice from the owning actor.
 * The API key is read from Saved/OpenAIKey.txt (one line, not in Git).
 * At session start, every .md file in Saved/Knowledge is appended to the instructions as lab knowledge.
 * Lip sync: the voice runs through Epic's real-time speech-to-face solver; LipSyncCurves holds the
 * MetaHuman face controls (CTRL_expressions_*) for the sample being heard now. The voice is delayed
 * slightly so the solver's lookahead is available before each sample plays.
 * Seeing: the camera service on the tracking PC sends a description of the people the camera sees as UDP packets to
 * the port in Saved/VisionPort.txt (not in Git); new descriptions are added to the session as silent context while
 * the visitor speaks, so the agent always knows its view.
 * Decisions: the triggers in Config/MRLabDecisions.json answer fixed questions on every transcript fragment of both
 * sides (reactions, requests, Frank's delivery); each answer is logged with its delay and tokens.
 */
UCLASS(ClassGroup = (MRLab), meta = (BlueprintSpawnableComponent))
class MRLABLIVE_API UMRLabLiveSession : public UActorComponent
{
	GENERATED_BODY()

public:
	UMRLabLiveSession();

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MRLab Live")
	FString Model = TEXT("gpt-live-1.1");

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MRLab Live")
	FString Voice = TEXT("marin");

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MRLab Live", meta = (MultiLine = true))
	FString Instructions;

	/** What the user has said so far in the current utterance (grows with each transcript fragment). */
	UPROPERTY(BlueprintAssignable, Category = "MRLab Live")
	FMRLabLiveText OnUserTranscript;

	/** What the agent has said so far in the current utterance. */
	UPROPERTY(BlueprintAssignable, Category = "MRLab Live")
	FMRLabLiveText OnAgentTranscript;

	/** The session ended: close reason from the server, or the connection error. */
	UPROPERTY(BlueprintAssignable, Category = "MRLab Live")
	FMRLabLiveText OnSessionClosed;

	/** Face controls for the voice sample being heard now. Empty until the first answer. */
	UPROPERTY(BlueprintReadOnly, Category = "MRLab Live")
	TMap<FName, float> LipSyncCurves;

	/** How much Frank is speaking at the sample being heard now: 0 silent, 1 speaking (the lip sync's mouth gate). */
	UPROPERTY(BlueprintReadOnly, Category = "MRLab Live")
	float SpeakingWeight = 0.f;

	/** Loudness (RMS, 0 to 1) of the visitor audio sent in the latest tick: the microphone, the test input, or in a
	 * replay the recorded input. The visitor's clip-on microphone also hears Frank's voice, more quietly (D113). */
	UPROPERTY(BlueprintReadOnly, Category = "MRLab Live")
	float VisitorLevel = 0.f;

	/** Every completed decision, parsed, on the game thread (C++ only). */
	FMRLabOnDecision OnDecision;

	/** FPlatformTime::Seconds() of the latest transcript fragment of Frank (0 before the first). */
	double LastFrankFragmentTime() const { return LastAgentFragment; }

	/** The visitor talks over Frank (D113): his voice stops at the end of the word being heard (at most 0.5 s on),
	 * and what the model still says of this answer is not played; his next answer plays again. */
	void StopAtWordEnd();
	/** The visitor speaks (owner, D126): while held, Frank's voice that has not started yet waits instead of playing;
	 * released, it plays, with the stream's silence in it dropped (the model waited for the visitor). */
	void HoldVoice(bool bHold);
	/** Loudness (RMS) of Frank's voice Seconds after the sample heard now, over Window seconds (0 where none waits). */
	float VoiceLevelAhead(float Seconds, float Window) const;
	/** Seconds of Frank's voice waiting because of HoldVoice. */
	float VoiceHeld() const { return bVoiceHeld ? PendingVoice.Num() / 24000.f : 0.f; }
	/** Seconds until the end of his newest words is heard (their text runs ahead of his voice), -1 if unknown. */
	float FrankWordsLeft() const;

	/** The voice sample (24 kHz, counted from the session start) being heard now. */
	int64 VoicePlayhead() const { return Playhead; }
	/** Seconds of Frank's voice waiting in the wave (still to play). */
	float VoiceWaiting() const { return VoiceQueued - Playhead > 0 ? (VoiceQueued - Playhead) / 24000.f : 0.f; }

	/** The voice sample at which Frank's words starting at StartMs (start_ms of his transcript) are heard, or -1 while
	 * the audio of his current utterance has not arrived yet. */
	int64 AgentFragmentSample(int32 StartMs) const;

	/** Tests: write every Live message sent and received to Saved/Recordings/<time>/events.jsonl. It contains the
	 * visitors' voices, so it is off by default. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MRLab Live|Tests")
	bool bRecordSession = false;

	/** Tests: instead of the microphone, send this WAV file (24 kHz, mono, 16 bit) as the visitor's voice, then silence. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MRLab Live|Tests")
	FString TestInputWav;

	/** Tests: instead of connecting, play back a recording (a folder with events.jsonl): Frank's voice, lip sync,
	 * transcripts and decisions, with their original timing. Nothing is sent. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MRLab Live|Tests")
	FString ReplayFolder;

	UFUNCTION(BlueprintCallable, Category = "MRLab Live")
	void StartSession();

	UFUNCTION(BlueprintCallable, Category = "MRLab Live")
	void StopSession();

	/** Mood input of the lip sync model from the next 20 ms step on: index of Epic's EAudioDrivenAnimationMood
	 * (0 neutral, 1 happy, 2 sad, 3 disgust, 4 anger, 5 surprise, 6 fear, 10 confident, 14 excited, 15 bored,
	 * 17 playful, 19 confused) with its intensity; 255 = detected from the voice (the default). */
	UFUNCTION(BlueprintCallable, Category = "MRLab Live")
	void SetLipSyncMood(int32 Mood, float Intensity);

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
	void HandleMessage(const FString& Message);
	void HandleDecision(const FJsonObject& Event, const FString& Message);
	void Send(const TSharedRef<FJsonObject>& Event);
	void StartVoice();
	void StartMicrophone();
	void StartReplay();
	void Record(bool bSent, const FString& Message);
	void Shutdown(const FString& Reason);
	void AddTranscript(bool bUser, const FString& Delta);
	void QueueVoice(const int16* Samples, int32 NumSamples);   // received voice
	void ReleaseVoice();                                        // each tick: received voice into the wave
	void EnqueueVoice(const int16* Samples, int32 NumSamples);  // into the wave and the lip sync
	void UpdateLipSync();
	void OpenViewSocket();
	void CloseViewSocket();
	void ReceiveViews();
	void SetBlind(const FString& Reason);
	void AppendView(const FString& Text);

	// Runs on the audio capture thread.
	void OnMicAudio(const float* Samples, int32 NumSamples);

	TSharedPtr<FLiveSocket> Socket;
	bool bStarted = false;

	UPROPERTY()
	TObjectPtr<UAudioCapture> Mic;

	UPROPERTY()
	TObjectPtr<UAudioComponent> Speaker;

	UPROPERTY()
	TObjectPtr<UMRLabVoiceWave> VoiceWave;

	FAudioGeneratorHandle MicHandle;
	int32 MicChannels = 1;
	int32 MicRate = 48000;
	Audio::FResampler Resampler;
	TArray<float> MicMono;
	TArray<float> MicResampled;

	// 24 kHz mono PCM16 waiting to be sent, filled on the audio thread.
	FCriticalSection MicLock;
	TArray<int16> MicPcm;

	// Solver model asset, kept here so it is not garbage collected while the solver uses it.
	UPROPERTY()
	TObjectPtr<UObject> LipSyncModel;

	// Solver and its thread; the game thread reads its frames under its lock.
	TSharedPtr<FLipSync> LipSync;

	// Voice samples queued into VoiceWave so far, including inserted delay silence.
	int64 VoiceQueued = 0;
	// The voice sample being played now (set in UpdateLipSync).
	int64 Playhead = 0;
	// Voice clock of Frank's current utterance: its first fragment's start_ms and the voice sample where its audio
	// starts (-1 until that audio arrives). Transcript times and audio positions differ by a constant within an
	// utterance (README 4.13), so start_ms maps to samples from this anchor.
	int32 AgentAnchorMs = -1;
	int64 AgentAnchorSample = -1;
	double LastAgentFragment = 0.0; // FPlatformTime::Seconds() of Frank's latest transcript fragment
	TArray<int16> PendingVoice; // received, goes into the wave at the next ReleaseVoice (later while held)
	bool bVoiceHeld = false;    // HoldVoice: the visitor speaks
	int64 DroppedSilence = 0; // samples of silence dropped to catch up (D111), logged when done
	int32 SilentFrames = 0;   // consecutive 10 ms frames of exact silence in the released voice
	int32 LastAgentEndMs = -1; // end_ms of Frank's newest transcript fragment
	// Stopping at a word end (D113): Finishing plays on until the word ends, Dropping leaves out the rest of the answer.
	enum class EVoiceCut : uint8 { None, Finishing, Dropping };
	EVoiceCut VoiceCut = EVoiceCut::None;
	int32 FinishLeft = 0;   // samples he may still say to end the word
	float CutPeak = 0.f;    // loudest 10 ms of the voice since the cut
	int32 CutQuietFrames = 0;
	double CutAt = 0.0;
	int64 MuteFrom = 0;     // voice samples silenced in the wave: their lip sync frames are not shown
	int64 MuteTo = 0;
	int64 SilencedSamples = 0;  // silenced, not yet told to the lip sync
	TMap<FName, float> MuteHold; // the lip sync face when the word ended, held while the rest is silent
	bool bMuteHeld = false;
	bool WordEnds(const int16* Frame, int32 Num);
	// The voice ran out without trailing silence (a pause in the stream, an interruption): the face returns to rest.
	double LastLipSyncTime = 0.0;
	float DryFade = 1.f;

	FString UserText;
	FString AgentText;
	bool bLastSpeakerUser = false;
	double LastUserDelta = 0.0; // time of the latest user transcript fragment

	// Frank's eyes: views from the camera service (UDP, port in Saved/VisionPort.txt) while the session runs, added to
	// the session only while the visitor speaks.
	class FSocket* ViewSocket = nullptr;
	double LastViewPacket = 0.0;
	bool bViewReceived = false;
	FString NewestView;  // the newest description, or BlindView
	double NewestViewTaken = 0.0; // when its picture was taken (FPlatformTime::Seconds)
	FString LastView;    // the last view added to the session
	int32 ViewCount = 0; // views added to this session, numbered in the context
	bool bBlind = false; // the camera service is down or its camera stopped

	// Decisions (Config/MRLabDecisions.json): items appended once at session start; transcript fragments by event_id,
	// to log how long each decision took after its fragment arrived.
	TArray<FString> DecisionItems;
	TMap<FString, FMRLabFragment> Fragments;
	int32 DecisionCount = 0;
	int64 DecisionInputTokens = 0;
	int64 DecisionCachedTokens = 0;

	// Recording (bRecordSession): one JSON line per message, with seconds since the session started.
	TUniquePtr<FArchive> RecordFile;
	double RecordStart = 0.0;

	// Test input (TestInputWav): 24 kHz PCM sent in real time from session start.
	TArray<int16> TestPcm;
	int64 TestSent = 0;
	double TestStart = 0.0;
	bool bTestInput = false;

	// Replay (ReplayFolder): received messages with their time since session start.
	TArray<TPair<double, FString>> ReplayEvents;
	TArray<TPair<double, float>> ReplayLevels; // recorded visitor audio: time, RMS
	int32 ReplayLevelNext = 0;
	int32 ReplayNext = 0;
	double ReplayStart = 0.0;
	bool bReplaying = false;
};
