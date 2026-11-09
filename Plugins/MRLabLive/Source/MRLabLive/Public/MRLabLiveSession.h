#pragma once

#include "CoreMinimal.h"
#include "AudioResampler.h"
#include "Components/ActorComponent.h"
#include "Generators/AudioGenerator.h"
#include "MRLabLiveSession.generated.h"

class FLiveSocket;
struct FLipSync;
class FJsonObject;
class UAudioCapture;
class UAudioComponent;
class USoundWaveProcedural;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_OneParam(FMRLabLiveText, const FString&, Text);

/**
 * Spoken conversation with OpenAI gpt-live-1 through the Live API (WebSocket over WinHttp, Windows only).
 * Streams the default microphone to the model and plays the agent's voice from the owning actor.
 * The API key is read from Saved/OpenAIKey.txt (one line, not in Git).
 * At session start, every .md file in Saved/Knowledge is appended to the instructions as lab knowledge.
 * Lip sync: the voice runs through Epic's real-time speech-to-face solver; LipSyncCurves holds the
 * MetaHuman face controls (CTRL_expressions_*) for the sample being heard now. The voice is delayed
 * slightly so the solver's lookahead is available before each sample plays.
 * Seeing: the camera service on the tracking PC sends a description of the people the camera sees as UDP packets to
 * the port in Saved/VisionPort.txt (not in Git); new descriptions are added to the session as silent context while
 * the visitor speaks, so the agent always knows its view.
 */
UCLASS(ClassGroup = (MRLab), meta = (BlueprintSpawnableComponent))
class MRLABLIVE_API UMRLabLiveSession : public UActorComponent
{
	GENERATED_BODY()

public:
	UMRLabLiveSession();

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MRLab Live")
	FString Model = TEXT("gpt-live-1");

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

	UFUNCTION(BlueprintCallable, Category = "MRLab Live")
	void StartSession();

	UFUNCTION(BlueprintCallable, Category = "MRLab Live")
	void StopSession();

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

private:
	void HandleMessage(const FString& Message);
	void Send(const TSharedRef<FJsonObject>& Event);
	void StartAudio();
	void Shutdown(const FString& Reason);
	void AddTranscript(bool bUser, const FString& Delta);
	void QueueVoice(const int16* Samples, int32 NumSamples);
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
	TObjectPtr<USoundWaveProcedural> VoiceWave;

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
};
