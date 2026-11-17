#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "MRLabGaze.h"
#include "MRLabBehaviorComponent.generated.h"

class UMRLabLiveSession;
class USceneComponent;
class USkeletalMeshComponent;
struct FMRLabDecision;

/**
 * Frank's emotions, face expressions, eyes and blinks (README 4.10, 4.14; Steps 9B, 9C). Reads the Decisions answers of
 * the Live session on the same actor: the visitor's words move fast emotions (amused, concerned, annoyed, ...) through
 * gates for freshness, confirmation and reversals; Frank's own delivery sets the lip sync mood at the moment his words
 * are heard. The expression layer turns the emotions into MetaHuman face controls, which the MRLab Face animation node
 * adds to the lip sync. Who speaks (voice, microphone level) drives where he looks (the tracked visitor of NDC_Basic,
 * read only, or his own business) and when he blinks; the eye and blink controls go through the same node, the head
 * target into the body post-process AnimBP. All numbers come from Config/MRLabBehavior.json, read at BeginPlay.
 */
UCLASS(ClassGroup = (MRLab), meta = (BlueprintSpawnableComponent))
class MRLABLIVE_API UMRLabBehaviorComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UMRLabBehaviorComponent();

	/** Tests: write the emotion state and the face controls 30 times a second to Saved/Recordings/<time>-behavior.jsonl. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "MRLab Behaviour|Tests")
	bool bTraceBehavior = false;

	/** Tests: show one expression category (as in Config/MRLabBehavior.json) at a fixed activation 0..1, without gates
	 * or easing, also in the editor; None ends the preview. */
	UFUNCTION(BlueprintCallable, Category = "MRLab Behaviour")
	void PreviewExpression(FName Category, float Activation);

	/** Tests: hold one face control at a value (the eye curves stop following the gaze while any is held, and the head
	 * target is not written); None releases all. */
	UFUNCTION(BlueprintCallable, Category = "MRLab Behaviour")
	void PreviewFaceControl(FName Control, float Value);

	/** The face controls the expression layer adds now, already weighted for speaking. Game thread (MRLab Face node). */
	const TArray<TPair<FName, float>>& GetFaceCurves() const { return FaceCurves; }
	/** Face controls that replace the lip sync's: the eye look curves (and held test controls). */
	const TArray<TPair<FName, float>>& GetOverrideCurves() const { return OverrideCurves; }
	/** Blink controls; the node takes the larger of these and the lip sync's. */
	const TArray<TPair<FName, float>>& GetBlinkCurves() const { return BlinkCurves; }

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	struct FCategory
	{
		FName Name;
		float Hold = 3.f;     // seconds the emotion holds after its last impulse
		float Gain = 0.8f;    // persona gain on the impact
		float Valence = 0.f;  // -1 negative, 0 neutral, 1 positive (reversals, slow mood)
		float Flash = 0.f;    // extra short peak on onset, relative to the impulse
		TArray<TPair<FName, float>> Recipe; // face control -> weight at full activation
		float Activation = 0.f;
		double HoldUntil = 0.0;
		double LastApplied = -1e9;
		float Shown = 0.f;      // eased activation on the face
		float FlashLevel = 0.f; // decaying onset peak
	};
	struct FScheduled // something of Frank's that starts when his words are heard
	{
		int32 StartMs = -1;
		double Created = 0.0;
		int32 Mood = -1;      // lip sync mood, or -1
		float Intensity = 0.f;
		FName Category;       // expression category, or None
		float Value = 0.f;
		bool bTurnFinal = false; // Decisions said these are the last words of his turn
		FString Text;
	};
	struct FCandidate // a reaction waiting for confirmation by the next fragment
	{
		FName Category;
		double FragmentArrived = 0.0;
	};

	bool LoadSettings();
	void HandleDecision(const FMRLabDecision& Decision);
	void HandleVisitor(const FMRLabDecision& Decision);
	void HandleFrank(const FMRLabDecision& Decision);
	void Apply(FCategory& Category, float Value);
	void RunScheduled();
	void UpdateFace(float Speaking);
	void WriteTrace(float Speaking);
	FCategory* FindCategory(FName Name);
	float GroupWeight(FName Control, float Speaking) const;
	void FindParts();
	void UpdateEyes(float DeltaTime, float Speaking);

	TWeakObjectPtr<UMRLabLiveSession> Session;
	FDelegateHandle DecisionHandle;
	bool bLoaded = false;

	// Settings (Config/MRLabBehavior.json).
	TArray<FCategory> Categories;
	TArray<TPair<FName, float>> Baseline;
	float Strength = 0.5f;
	float RiseSeconds = 0.5f;
	float FallSeconds = 1.2f;
	float FlashSeconds = 0.2f;
	TMap<FName, int32> ControlGroup; // 0 upper face, 1 mouth corners, 2 rest of the mouth
	float SpeakingWeights[3] = { 1.f, 0.3f, 0.f };
	float BaseValence = -0.15f;
	float BaseArousal = -0.2f;
	float ReturnSeconds = 90.f;
	float OtherSideShare = 0.3f;
	float MinProbability = 0.55f;
	float MinConfidence = 0.4f;
	float MinImpact = 0.15f;
	float StrongImpact = 0.65f;
	float ConfirmSeconds = 3.f;
	float FreshSeconds = 2.f;
	float ReversalSeconds = 8.f;
	float ReversalProbability = 0.85f;
	bool bExplicitMoods = true;
	float MoodReleaseSeconds = 1.f;
	TMap<FName, TPair<int32, float>> DeliveryMoods;   // delivery -> lip sync mood and intensity
	TMap<FName, FName> DeliveryCategories;            // delivery -> expression category while he says it
	TMap<FName, float> DeliveryValence;               // delivery -> slow mood

	// State.
	float Valence = -0.15f;
	float Arousal = -0.2f;
	float Rapport = 0.2f;
	double LastVisitorFragment = 0.0; // arrival of the newest visitor fragment that was applied
	TOptional<FCandidate> Candidate;
	TArray<FScheduled> Scheduled;
	int32 CurrentMood = 255;
	float CurrentIntensity = 0.f;
	double SilentSince = 0.0;
	FName PreviewCategory;
	float PreviewActivation = 0.f;

	TArray<TPair<FName, float>> FaceCurves;

	// Eyes and blinks (9C).
	FMRLabTurns Turns;
	FMRLabGaze Gaze;
	FMRLabBlinks Blinks;
	EMRLabTurn LoggedTurn = EMRLabTurn::Outside;
	double TurnDoneAt = 0.0;  // latest visitor decision saying their turn is done or asks Frank
	double TurnFinalAt = 0.0; // when the words Decisions marked as the end of Frank's turn were heard
	TWeakObjectPtr<AActor> Ndc;
	TWeakObjectPtr<USceneComponent> Rig;
	TWeakObjectPtr<USkeletalMeshComponent> FaceMesh;
	TWeakObjectPtr<USkeletalMeshComponent> BodyMesh;
	double NextPartSearch = 0.0;
	TMap<FName, float> PreviewControls;
	TArray<TPair<FName, float>> OverrideCurves;
	TArray<TPair<FName, float>> BlinkCurves;
	double GazeCost = 0.0;
	int32 GazeTicks = 0;
	float TraceVisitorAngle = -1.f; // degrees between where the eyes look and the visitor point, seen from the eyes
	float TraceVisitorDistance = 0.f;
	float TraceModelBlink = 0.f;
	float TraceEyeError[2] = { -1.f, -1.f }; // degrees between each eye bone's look axis (last pose) and its gaze direction
	bool bTraceTracked = false;

	TUniquePtr<FArchive> TraceFile;
	double TraceStart = 0.0;
	double TraceNext = 0.0;
};
