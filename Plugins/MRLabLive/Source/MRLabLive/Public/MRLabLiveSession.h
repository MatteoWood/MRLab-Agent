#pragma once

#include "CoreMinimal.h"
#include "AudioResampler.h"
#include "Components/ActorComponent.h"
#include "Generators/AudioGenerator.h"
#include "MRLabLiveSession.generated.h"

class FLiveSocket;
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

	FString UserText;
	FString AgentText;
	bool bLastSpeakerUser = false;
};
