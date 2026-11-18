#include "MRLabBehaviorComponent.h"

#include "Animation/AnimInstance.h"
#include "Components/SkeletalMeshComponent.h"
#include "Dom/JsonObject.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "MRLabLiveSession.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

DEFINE_LOG_CATEGORY_STATIC(LogMRLabBehavior, Log, All);

namespace
{
	constexpr int32 AutomaticMood = 255;     // the lip sync model detects the mood from the voice
	constexpr double ScheduledMaxAge = 15.0; // Frank's words not heard within this time are dropped
	constexpr double TraceInterval = 1.0 / 30.0;
	constexpr float ScoreTop = 3.f;          // impact and strength are 4-level scores, 0 (flat) to 3 (strong), Config/MRLabDecisions.json

	float Ease(float Value, float Target, float Seconds, float DeltaTime)
	{
		// About 95 % of the way after Seconds.
		return Seconds <= 0.f ? Target : Value + (Target - Value) * (1.f - FMath::Exp(-3.f * DeltaTime / Seconds));
	}

	// One step of two critically damped stages in series towards Goal (95 % after Seconds): eased in and out.
	void Ease2(float& A, float& AVel, float& X, float& XVel, float Goal, float Seconds, float DeltaTime)
	{
		const float W = 7.75f / FMath::Max(Seconds, 0.05f);
		const float Dt = FMath::Min(DeltaTime, 0.25f);
		auto Stage = [W, Dt](float& Value, float& Vel, float Target)
		{
			const float D = Value - Target;
			const float C = Vel + W * D;
			const float E = FMath::Exp(-W * Dt);
			Value = Target + (D + C * Dt) * E;
			Vel = (Vel - W * C * Dt) * E;
		};
		Stage(A, AVel, Goal);
		Stage(X, XVel, A);
	}

	float NumberOr(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field, float Default)
	{
		double Value = Default;
		return Object.IsValid() && Object->TryGetNumberField(Field, Value) ? float(Value) : Default;
	}

	const FName FaceName(TEXT("Face"));
	const FName BodyName(TEXT("Body"));
	const FName RigName(TEXT("Rig"));
	const FName HeadBone(TEXT("head"));
	const FName EyeBones[2] = { FName(TEXT("FACIAL_L_Eye")), FName(TEXT("FACIAL_R_Eye")) };
	const FName BlinkCurveNames[2] = { FName(TEXT("CTRL_expressions_eyeBlinkL")), FName(TEXT("CTRL_expressions_eyeBlinkR")) };

	const TCHAR* GazeKindName(FMRLabGaze::EKind Kind)
	{
		switch (Kind)
		{
		case FMRLabGaze::EKind::Visitor: return TEXT("visitor");
		case FMRLabGaze::EKind::Own: return TEXT("own");
		case FMRLabGaze::EKind::Aversion: return TEXT("aversion");
		case FMRLabGaze::EKind::Thinking: return TEXT("thinking");
		case FMRLabGaze::EKind::Glance: return TEXT("glance");
		}
		return TEXT("?");
	}
}

UMRLabBehaviorComponent::UMRLabBehaviorComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickGroup = TG_PrePhysics;
}

bool UMRLabBehaviorComponent::LoadSettings()
{
	const FString Path = FPaths::ProjectConfigDir() / TEXT("MRLabBehavior.json");
	FString Text;
	TSharedPtr<FJsonObject> Root;
	if (!FFileHelper::LoadFileToString(Text, *Path) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid())
	{
		UE_LOG(LogMRLabBehavior, Error, TEXT("Cannot read %s: no expressions"), *Path);
		return false;
	}

	Strength = NumberOr(Root, TEXT("strength"), Strength);
	RiseSeconds = NumberOr(Root, TEXT("rise_seconds"), RiseSeconds);
	FallSeconds = NumberOr(Root, TEXT("fall_seconds"), FallSeconds);
	FlashSeconds = NumberOr(Root, TEXT("flash_seconds"), FlashSeconds);
	Root->TryGetBoolField(TEXT("explicit_moods"), bExplicitMoods);
	MoodReleaseSeconds = NumberOr(Root, TEXT("mood_release_seconds"), MoodReleaseSeconds);
	MoodHoldSeconds = NumberOr(Root, TEXT("mood_hold_seconds"), MoodHoldSeconds);
	MoodRampPerSecond = NumberOr(Root, TEXT("mood_ramp_per_second"), MoodRampPerSecond);

	const TSharedPtr<FJsonObject>* Object = nullptr;
	if (Root->TryGetObjectField(TEXT("slow_mood"), Object))
	{
		BaseValence = NumberOr(*Object, TEXT("valence"), BaseValence);
		BaseArousal = NumberOr(*Object, TEXT("arousal"), BaseArousal);
		ReturnSeconds = NumberOr(*Object, TEXT("return_seconds"), ReturnSeconds);
		OtherSideShare = NumberOr(*Object, TEXT("frank_share"), OtherSideShare);
		Rapport = NumberOr(*Object, TEXT("rapport"), Rapport);
	}
	Valence = BaseValence;
	Arousal = BaseArousal;
	if (Root->TryGetObjectField(TEXT("gates"), Object))
	{
		MinProbability = NumberOr(*Object, TEXT("probability"), MinProbability);
		MinConfidence = NumberOr(*Object, TEXT("confidence"), MinConfidence);
		MinImpact = NumberOr(*Object, TEXT("impact"), MinImpact);
		StrongImpact = NumberOr(*Object, TEXT("strong_impact"), StrongImpact);
		ConfirmSeconds = NumberOr(*Object, TEXT("confirm_seconds"), ConfirmSeconds);
		FreshSeconds = NumberOr(*Object, TEXT("fresh_seconds"), FreshSeconds);
		ReversalSeconds = NumberOr(*Object, TEXT("reversal_seconds"), ReversalSeconds);
		ReversalProbability = NumberOr(*Object, TEXT("reversal_probability"), ReversalProbability);
	}

	// Groups for the speaking rule: the first matching prefix list wins (corners before the rest of the mouth).
	TArray<TArray<FString>> Prefixes = { {}, {}, {} };
	const TCHAR* GroupNames[3] = { TEXT("upper"), TEXT("corners"), TEXT("mouth") };
	if (Root->TryGetObjectField(TEXT("speaking"), Object))
	{
		for (int32 Group = 0; Group < 3; ++Group)
		{
			const TSharedPtr<FJsonObject>* GroupObject = nullptr;
			if ((*Object)->TryGetObjectField(GroupNames[Group], GroupObject))
			{
				SpeakingWeights[Group] = NumberOr(*GroupObject, TEXT("weight"), SpeakingWeights[Group]);
				const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
				if ((*GroupObject)->TryGetArrayField(TEXT("prefixes"), List))
				{
					for (const TSharedPtr<FJsonValue>& Value : *List)
					{
						Prefixes[Group].Add(Value->AsString());
					}
				}
			}
		}
	}
	auto Classify = [this, &Prefixes](FName Control)
	{
		const FString Name = Control.ToString();
		for (int32 Group : { 1, 2, 0 })
		{
			for (const FString& Prefix : Prefixes[Group])
			{
				if (Name.StartsWith(Prefix))
				{
					ControlGroup.Add(Control, Group);
					return;
				}
			}
		}
		ControlGroup.Add(Control, 0);
	};

	Baseline.Reset();
	if (Root->TryGetObjectField(TEXT("baseline"), Object))
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Object)->Values)
		{
			Baseline.Emplace(FName(Pair.Key), float(Pair.Value->AsNumber()));
			Classify(FName(Pair.Key));
		}
	}

	Categories.Reset();
	if (Root->TryGetObjectField(TEXT("categories"), Object))
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Object)->Values)
		{
			if (Pair.Value->Type != EJson::Object)
			{
				continue;
			}
			const TSharedPtr<FJsonObject> Entry = Pair.Value->AsObject();
			FCategory& Category = Categories.AddDefaulted_GetRef();
			Category.Name = FName(Pair.Key);
			Category.Hold = NumberOr(Entry, TEXT("hold"), Category.Hold);
			Category.Gain = NumberOr(Entry, TEXT("gain"), Category.Gain);
			Category.Valence = NumberOr(Entry, TEXT("valence"), Category.Valence);
			Category.Flash = NumberOr(Entry, TEXT("flash"), Category.Flash);
			const TSharedPtr<FJsonObject>* Recipe = nullptr;
			if (Entry.IsValid() && Entry->TryGetObjectField(TEXT("recipe"), Recipe))
			{
				for (const TPair<FString, TSharedPtr<FJsonValue>>& Control : (*Recipe)->Values)
				{
					Category.Recipe.Emplace(FName(Control.Key), float(Control.Value->AsNumber()));
					Classify(FName(Control.Key));
				}
			}
		}
	}

	DeliveryMoods.Reset();
	DeliveryCategories.Reset();
	DeliveryValence.Reset();
	if (Root->TryGetObjectField(TEXT("delivery"), Object))
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Object)->Values)
		{
			if (Pair.Value->Type != EJson::Object)
			{
				continue; // notes such as "_about"
			}
			const TSharedPtr<FJsonObject> Entry = Pair.Value->AsObject();
			double Mood = -1.0;
			if (Entry->TryGetNumberField(TEXT("mood"), Mood) && Mood >= 0.0)
			{
				DeliveryMoods.Add(FName(Pair.Key), { int32(Mood), NumberOr(Entry, TEXT("intensity"), 0.5f) });
			}
			FString Category;
			if (Entry->TryGetStringField(TEXT("category"), Category))
			{
				DeliveryCategories.Add(FName(Pair.Key), FName(Category));
			}
			DeliveryValence.Add(FName(Pair.Key), NumberOr(Entry, TEXT("valence"), 0.f));
		}
	}

	if (Root->TryGetObjectField(TEXT("notice"), Object))
	{
		FString Category;
		if ((*Object)->TryGetStringField(TEXT("category"), Category))
		{
			NoticeCategory = FName(Category);
		}
		NoticeValue = NumberOr(*Object, TEXT("value"), NoticeValue);
	}
	if (Root->TryGetObjectField(TEXT("interrupted"), Object))
	{
		FString Name;
		if ((*Object)->TryGetStringField(TEXT("category"), Name))
		{
			InterruptCategory = FName(Name);
		}
		if ((*Object)->TryGetStringField(TEXT("then"), Name))
		{
			ListenCategory = FName(Name);
		}
		InterruptValue = NumberOr(*Object, TEXT("value"), InterruptValue);
		ListenValue = NumberOr(*Object, TEXT("then_value"), ListenValue);
		ListenAfter = NumberOr(*Object, TEXT("then_after"), ListenAfter);
		InterruptInto = NumberOr(*Object, TEXT("into"), InterruptInto);
		InterruptLevel = NumberOr(*Object, TEXT("level"), InterruptLevel);
		InterruptMinSpeech = NumberOr(*Object, TEXT("min_speech"), InterruptMinSpeech);
		InterruptQuietGap = NumberOr(*Object, TEXT("quiet_gap"), InterruptQuietGap);
		FinishedWithin = NumberOr(*Object, TEXT("finished_within"), FinishedWithin);
		InterruptCooldown = NumberOr(*Object, TEXT("cooldown"), InterruptCooldown);
		InterruptLookSeconds = NumberOr(*Object, TEXT("look_seconds"), InterruptLookSeconds);
		HeadBackDegrees = NumberOr(*Object, TEXT("head_back_degrees"), HeadBackDegrees);
	}
	if (Root->TryGetObjectField(TEXT("breath"), Object))
	{
		BreathDelay = NumberOr(*Object, TEXT("delay_after_text"), BreathDelay);
		BreathYieldDelay = NumberOr(*Object, TEXT("delay_after_turn_end"), BreathYieldDelay);
		BreathInSeconds = NumberOr(*Object, TEXT("in_seconds"), BreathInSeconds);
		BreathHoldMax = NumberOr(*Object, TEXT("hold_max"), BreathHoldMax);
		BreathOutSpeaking = NumberOr(*Object, TEXT("out_speaking"), BreathOutSpeaking);
		BreathOutRelease = NumberOr(*Object, TEXT("out_release"), BreathOutRelease);
		BreathChestDegrees = NumberOr(*Object, TEXT("chest_degrees"), BreathChestDegrees);
		BreathChestLift = NumberOr(*Object, TEXT("chest_lift_cm"), BreathChestLift);
		BreathShoulderDegrees = NumberOr(*Object, TEXT("shoulder_degrees"), BreathShoulderDegrees);
		BreathHeadDegrees = NumberOr(*Object, TEXT("head_degrees"), BreathHeadDegrees);
		BreathSmoothSeconds = NumberOr(*Object, TEXT("smooth_seconds"), BreathSmoothSeconds);
	}
	if (Root->TryGetObjectField(TEXT("turns"), Object))
	{
		Turns.Load(*Object);
	}
	if (Root->TryGetObjectField(TEXT("gaze"), Object))
	{
		Gaze.Load(*Object);
	}
	if (Root->TryGetObjectField(TEXT("blinks"), Object))
	{
		Blinks.Load(*Object);
	}

	bLoaded = true;
	UE_LOG(LogMRLabBehavior, Log, TEXT("Behaviour: %d expression categories, %d baseline controls, strength %.2f, explicit moods %s (%s)"),
		Categories.Num(), Baseline.Num(), Strength, bExplicitMoods ? TEXT("on") : TEXT("off"), *Path);
	return true;
}

void UMRLabBehaviorComponent::BeginPlay()
{
	Super::BeginPlay();
	LoadSettings();
	if (UMRLabLiveSession* Found = GetOwner() ? GetOwner()->FindComponentByClass<UMRLabLiveSession>() : nullptr)
	{
		Session = Found;
		DecisionHandle = Found->OnDecision.AddUObject(this, &UMRLabBehaviorComponent::HandleDecision);
		AddTickPrerequisiteComponent(Found); // the session's playhead and lip sync are current when this ticks
	}
	else
	{
		UE_LOG(LogMRLabBehavior, Warning, TEXT("No MRLab Live session on %s: the face shows only its baseline"), *GetNameSafe(GetOwner()));
	}
	FindParts();
}

void UMRLabBehaviorComponent::FindParts()
{
	AActor* Owner = GetOwner();
	if (!Owner)
	{
		return;
	}
	if (!FaceMesh.IsValid() || !BodyMesh.IsValid())
	{
		TArray<USkeletalMeshComponent*> Meshes;
		Owner->GetComponents(Meshes);
		for (USkeletalMeshComponent* Mesh : Meshes)
		{
			const bool bFace = Mesh->GetFName() == FaceName;
			if (!bFace && Mesh->GetFName() != BodyName)
			{
				continue;
			}
			TWeakObjectPtr<USkeletalMeshComponent>& Slot = bFace ? FaceMesh : BodyMesh;
			if (!Slot.IsValid())
			{
				Slot = Mesh;
				// Its animation updates after this component has written the eye, blink and head values.
				Mesh->AddTickPrerequisiteComponent(this);
			}
		}
	}
	if (!Ndc.IsValid() && GetWorld())
	{
		for (TActorIterator<AActor> It(GetWorld()); It; ++It)
		{
			if (It->GetClass()->GetName().StartsWith(TEXT("NDC_Basic")))
			{
				TArray<USceneComponent*> Parts;
				It->GetComponents(Parts);
				for (USceneComponent* Part : Parts)
				{
					if (Part->GetFName() == RigName)
					{
						Rig = Part;
					}
				}
				Ndc = *It;
				UE_LOG(LogMRLabBehavior, Log, TEXT("Gaze: visitor head from %s (Rig %s)"), *It->GetName(), Rig.IsValid() ? TEXT("found") : TEXT("missing"));
				break;
			}
		}
	}
}

void UMRLabBehaviorComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UMRLabLiveSession* Live = Session.Get())
	{
		Live->OnDecision.Remove(DecisionHandle);
	}
	if (GazeTicks > 0)
	{
		UE_LOG(LogMRLabBehavior, Log, TEXT("Eyes: %d updates, %.3f ms each; blinks: own %d, lip sync model %d"),
			GazeTicks, GazeCost / GazeTicks * 1000.0, Blinks.OwnCount, Blinks.ModelCount);
	}
	TraceFile.Reset();
	Super::EndPlay(EndPlayReason);
}

UMRLabBehaviorComponent::FCategory* UMRLabBehaviorComponent::FindCategory(FName Name)
{
	return Categories.FindByPredicate([Name](const FCategory& Category) { return Category.Name == Name; });
}

void UMRLabBehaviorComponent::HandleDecision(const FMRLabDecision& Decision)
{
	// Turn ends for the gaze (Appendix A thresholds).
	if (Decision.bVisitor)
	{
		const FMRLabAnswer* Done = Decision.Find(TEXT("turn_done"));
		const FMRLabAnswer* Asks = Decision.Find(TEXT("asks_frank"));
		if ((Done && Done->Value >= 0.65f) || (Asks && Asks->Value >= 0.6f))
		{
			TurnDoneAt = FPlatformTime::Seconds();
		}
	}
	if (Decision.bVisitor)
	{
		HandleVisitor(Decision);
	}
	else
	{
		HandleFrank(Decision);
	}
}

void UMRLabBehaviorComponent::HandleVisitor(const FMRLabDecision& Decision)
{
	const FMRLabAnswer* Reaction = Decision.Find(TEXT("reaction"));
	if (!Reaction || Reaction->Choice == TEXT("none"))
	{
		return;
	}
	FCategory* Category = FindCategory(Reaction->Choice);
	if (!Category)
	{
		return;
	}
	const FMRLabAnswer* ImpactAnswer = Decision.Find(TEXT("impact"));
	const float Probability = Reaction->Probability(Reaction->Choice);
	const float Impact = ImpactAnswer ? ImpactAnswer->Value / ScoreTop : 0.f; // 0 to 1: mild 0.33, clear 0.67, strong 1
	const double Now = FPlatformTime::Seconds();
	const FString Heard = FString::Printf(TEXT("\"%s\" %s p %.2f conf %.2f impact %.2f"), *Decision.Text, *Reaction->Choice.ToString(),
		Probability, Reaction->Confidence, Impact);

	// Gates (README 4.14): freshness, threshold, reversal, confirmation.
	if (Decision.Arrived - Decision.FragmentArrived > FreshSeconds)
	{
		UE_LOG(LogMRLabBehavior, Log, TEXT("Reaction dropped (stale, %.2f s): %s"), Decision.Arrived - Decision.FragmentArrived, *Heard);
		return;
	}
	if (Decision.FragmentArrived < LastVisitorFragment)
	{
		UE_LOG(LogMRLabBehavior, Log, TEXT("Reaction dropped (older than an applied one): %s"), *Heard);
		return;
	}
	if (Probability < MinProbability || Reaction->Confidence < MinConfidence || Impact < MinImpact)
	{
		UE_LOG(LogMRLabBehavior, Verbose, TEXT("Reaction below the thresholds: %s"), *Heard);
		return;
	}
	FCategory* Opposite = Category->Valence == 0.f ? nullptr : Categories.FindByPredicate([&](const FCategory& Other)
	{
		return Other.Valence * Category->Valence < 0.f && Other.Activation > 0.2f && Now - Other.LastApplied < ReversalSeconds;
	});
	if (Opposite && Probability < ReversalProbability)
	{
		UE_LOG(LogMRLabBehavior, Log, TEXT("Reaction dropped (reverses %s within %.0f s, needs p %.2f): %s"),
			*Opposite->Name.ToString(), ReversalSeconds, ReversalProbability, *Heard);
		return;
	}
	const bool bConfirmed = Impact >= StrongImpact
		|| (Candidate.IsSet() && Candidate->Category == Category->Name && Decision.FragmentArrived - Candidate->FragmentArrived <= ConfirmSeconds);
	if (!bConfirmed)
	{
		Candidate = FCandidate{ Category->Name, Decision.FragmentArrived };
		UE_LOG(LogMRLabBehavior, Log, TEXT("Reaction waits for confirmation: %s"), *Heard);
		return;
	}
	Candidate.Reset();
	if (Opposite)
	{
		// Through neutral: the old feeling ends now and fades while the new one rises.
		Opposite->Activation = 0.f;
		Opposite->HoldUntil = 0.0;
	}
	const float RapportGain = Category->Valence > 0.f ? 0.8f + 0.4f * Rapport : 1.f;
	const float Value = FMath::Min(1.f, Impact * Category->Gain * RapportGain);
	Apply(*Category, Value);
	LastVisitorFragment = Decision.FragmentArrived;
	if (Category->Valence > 0.f)
	{
		Rapport = FMath::Min(1.f, Rapport + 0.03f * Value);
	}
	UE_LOG(LogMRLabBehavior, Log, TEXT("Reaction %s %.2f (%.2f s after the fragment): %s"), *Category->Name.ToString(), Value,
		Now - Decision.FragmentArrived, *Heard);
}

void UMRLabBehaviorComponent::HandleFrank(const FMRLabDecision& Decision)
{
	const FMRLabAnswer* Delivery = Decision.Find(TEXT("delivery"));
	const FMRLabAnswer* Final = Decision.Find(TEXT("turn_final"));
	const bool bTurnFinal = Final && Final->Value >= 0.6f;
	// The newest of his words (their text runs ahead of his voice; when he stops, these are the last ones heard).
	// Decisions can arrive out of order: one on older words does not count.
	if (Decision.StartMs < 0 || Decision.StartMs >= LastFrankDecisionMs)
	{
		LastFrankDecisionMs = Decision.StartMs;
		const FString Words = Decision.Text.TrimEnd();
		bLastFrankFinished = bTurnFinal && (Words.EndsWith(TEXT(".")) || Words.EndsWith(TEXT("!")) || Words.EndsWith(TEXT("?")));
	}
	if (!Delivery || Delivery->Probability(Delivery->Choice) < MinProbability || Delivery->Confidence < MinConfidence)
	{
		if (bTurnFinal)
		{
			FScheduled Item;
			Item.StartMs = Decision.StartMs;
			Item.Created = FPlatformTime::Seconds();
			Item.Text = Decision.Text;
			Item.bTurnFinal = true;
			Scheduled.Add(MoveTemp(Item));
		}
		return;
	}
	const FMRLabAnswer* StrengthAnswer = Decision.Find(TEXT("strength"));
	const FMRLabAnswer* Sound = Decision.Find(TEXT("sound"));
	const float DeliveryStrength = StrengthAnswer ? StrengthAnswer->Value / ScoreTop : 0.5f;
	FName Key = Delivery->Choice;
	if (Key == TEXT("amused") && Sound && Sound->Choice == TEXT("laugh"))
	{
		Key = TEXT("amused_laugh");
	}

	// His own words feed the slow mood a little.
	Valence = FMath::Clamp(Valence + OtherSideShare * DeliveryValence.FindRef(Delivery->Choice) * DeliveryStrength * 0.15f, -1.f, 1.f);

	FScheduled Item;
	Item.StartMs = Decision.StartMs;
	Item.Created = FPlatformTime::Seconds();
	Item.Text = Decision.Text;
	Item.bTurnFinal = bTurnFinal;
	if (bExplicitMoods)
	{
		if (const TPair<int32, float>* Mood = DeliveryMoods.Find(Key))
		{
			Item.Mood = Mood->Key;
			Item.Intensity = Mood->Value;
		}
	}
	if (const FName* Category = DeliveryCategories.Find(Delivery->Choice))
	{
		Item.Category = *Category;
		Item.Value = FMath::Clamp(DeliveryStrength, 0.3f, 1.f);
	}
	if (Item.Mood >= 0 || !Item.Category.IsNone() || Item.bTurnFinal)
	{
		Scheduled.Add(MoveTemp(Item));
	}
}

void UMRLabBehaviorComponent::Apply(FCategory& Category, float Value)
{
	const double Now = FPlatformTime::Seconds();
	Category.Activation = FMath::Max(Category.Activation, Value); // a maximum, never a sum
	Category.HoldUntil = FMath::Max(Category.HoldUntil, Now + Category.Hold);
	Category.LastApplied = Now;
	Category.FlashLevel = FMath::Max(Category.FlashLevel, Category.Flash * Value);
	Valence = FMath::Clamp(Valence + Category.Valence * Value * 0.15f, -1.f, 1.f);
	Arousal = FMath::Clamp(Arousal + Value * 0.1f, -1.f, 1.f);
}

void UMRLabBehaviorComponent::RunScheduled()
{
	UMRLabLiveSession* Live = Session.Get();
	if (!Live)
	{
		Scheduled.Reset();
		return;
	}
	const double Now = FPlatformTime::Seconds();
	const int64 Playhead = Live->VoicePlayhead();
	for (int32 Index = 0; Index < Scheduled.Num(); )
	{
		FScheduled& Item = Scheduled[Index];
		const int64 Sample = Live->AgentFragmentSample(Item.StartMs);
		if (Sample < 0 || Playhead < Sample)
		{
			if (Now - Item.Created > ScheduledMaxAge)
			{
				Scheduled.RemoveAt(Index);
			}
			else
			{
				++Index;
			}
			continue;
		}
		// His words are being heard now.
		if (Item.Mood >= 0)
		{
			HearMood(Item.Mood, Item.Intensity, Sample, Playhead, Now - Item.Created, Item.Text);
		}
		if (FCategory* Category = FindCategory(Item.Category))
		{
			Apply(*Category, Item.Value * Category->Gain);
		}
		if (Item.bTurnFinal)
		{
			TurnFinalAt = Now;
		}
		Scheduled.RemoveAt(Index);
	}
}

void UMRLabBehaviorComponent::HearMood(int32 Mood, float Intensity, int64 Sample, int64 Playhead, double Age, const FString& Text)
{
	// A new mood needs the same answer twice in a row (or no explicit mood yet) and the current one held MoodHoldSeconds.
	const double Now = FPlatformTime::Seconds();
	if (Mood == TargetMood)
	{
		TargetIntensity = Intensity;
		CandidateMood = -1;
		return;
	}
	const bool bConfirmed = TargetMood == AutomaticMood || Mood == CandidateMood;
	CandidateMood = Mood;
	CandidateIntensity = Intensity;
	bCandidateConfirmed = bConfirmed;
	if (!bConfirmed || Now - TargetSince < MoodHoldSeconds)
	{
		return;
	}
	TargetMood = Mood;
	TargetIntensity = Intensity;
	TargetSince = Now;
	CandidateMood = -1;
	bCandidateConfirmed = false;
	UE_LOG(LogMRLabBehavior, Log, TEXT("Lip sync mood %d (%.2f) at voice sample %lld, playhead %lld (%.2f s after the text): \"%s\""),
		Mood, Intensity, Sample, Playhead, Age, *Text);
}

void UMRLabBehaviorComponent::UpdateMood(float DeltaTime)
{
	// A mood heard twice while the current one was still held takes over once the hold time is over.
	const double Now = FPlatformTime::Seconds();
	if (CandidateMood >= 0 && bCandidateConfirmed && Now - TargetSince >= MoodHoldSeconds)
	{
		TargetMood = CandidateMood;
		TargetIntensity = CandidateIntensity;
		TargetSince = Now;
		CandidateMood = -1;
		bCandidateConfirmed = false;
		UE_LOG(LogMRLabBehavior, Log, TEXT("Lip sync mood %d (%.2f) after the hold time"), TargetMood, TargetIntensity);
	}
	// Fade: the mood sent moves towards the target through a low strength, never jumping between two moods.
	constexpr float Floor = 0.05f;
	const float Step = MoodRampPerSecond * DeltaTime;
	if (CurrentMood == TargetMood)
	{
		CurrentIntensity = TargetMood == AutomaticMood ? 0.f
			: CurrentIntensity + FMath::Clamp(TargetIntensity - CurrentIntensity, -Step, Step);
	}
	else if (CurrentMood == AutomaticMood)
	{
		CurrentMood = TargetMood;
		CurrentIntensity = Floor;
	}
	else
	{
		CurrentIntensity -= Step;
		if (CurrentIntensity <= Floor)
		{
			CurrentMood = TargetMood;
			CurrentIntensity = TargetMood == AutomaticMood ? 0.f : Floor;
		}
	}
	if (CurrentMood != SentMood || FMath::Abs(CurrentIntensity - SentIntensity) > 0.01f)
	{
		if (UMRLabLiveSession* Live = Session.Get())
		{
			Live->SetLipSyncMood(CurrentMood, CurrentIntensity);
		}
		SentMood = CurrentMood;
		SentIntensity = CurrentIntensity;
	}
}

void UMRLabBehaviorComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	if (!bLoaded)
	{
		return;
	}
	const UMRLabLiveSession* Live = Session.Get();
	const float Speaking = Live ? Live->SpeakingWeight : 0.f;
	if (!PreviewCategory.IsNone())
	{
		UpdateFace(0.f);
		UpdateEyes(DeltaTime, 0.f);
		return;
	}

	RunScheduled();
	const double Now = FPlatformTime::Seconds();

	// Back to the voice's own mood after he has been silent for a while (faded out).
	if (Speaking > 0.05f)
	{
		SilentSince = Now;
	}
	else if (TargetMood != AutomaticMood && Now - SilentSince > MoodReleaseSeconds)
	{
		TargetMood = AutomaticMood;
		TargetIntensity = 0.f;
		TargetSince = Now;
		CandidateMood = -1;
		bCandidateConfirmed = false;
	}
	UpdateMood(DeltaTime);

	for (FCategory& Category : Categories)
	{
		if (Now > Category.HoldUntil)
		{
			Category.Activation = Ease(Category.Activation, 0.f, FallSeconds, DeltaTime);
		}
		// The face follows activation plus any onset peak through two eased stages: no jumps, soft start and end.
		Category.FlashLevel = Ease(Category.FlashLevel, 0.f, FlashSeconds * 2.f, DeltaTime);
		const float Goal = FMath::Min(1.f, Category.Activation + Category.FlashLevel);
		const bool bRising = Goal > Category.Shown;
		Ease2(Category.ShownA, Category.ShownAVel, Category.Shown, Category.ShownVel, Goal,
			bRising ? (Category.Flash > 0.f ? FlashSeconds : RiseSeconds) : FallSeconds, DeltaTime);
		Category.Shown = FMath::Clamp(Category.Shown, 0.f, 1.f);
	}
	const float Return = 1.f - FMath::Exp(-DeltaTime / FMath::Max(ReturnSeconds, 1.f));
	Valence += (BaseValence - Valence) * Return;
	Arousal += (BaseArousal - Arousal) * Return;

	UpdateFace(Speaking);
	UpdateEyes(DeltaTime, Speaking);
	WriteTrace(Speaking);
}

void UMRLabBehaviorComponent::UpdateEyes(float DeltaTime, float Speaking)
{
	const double Now = FPlatformTime::Seconds();
	if (Now >= NextPartSearch && (!FaceMesh.IsValid() || !BodyMesh.IsValid() || !Ndc.IsValid()))
	{
		NextPartSearch = Now + 1.0;
		FindParts();
	}
	const UMRLabLiveSession* Live = Session.Get();
	const EMRLabTurn Before = Turns.State;
	const bool bWasLookingAround = Gaze.Kind == FMRLabGaze::EKind::Own;
	Turns.Update(Now, Speaking, Live ? Live->VisitorLevel : 0.f, TurnDoneAt, TurnFinalAt);
	// After a real silence (a pause or no conversation) while he looked around, the visitor's voice makes him look back
	// with a small raise of the brows.
	if (Turns.State == EMRLabTurn::Listening && (Before == EMRLabTurn::Pause || Before == EMRLabTurn::Outside) && bWasLookingAround)
	{
		if (FCategory* Category = FindCategory(NoticeCategory))
		{
			Apply(*Category, NoticeValue);
			UE_LOG(LogMRLabBehavior, Log, TEXT("Noticed the visitor after a silence: %s %.2f"), *NoticeCategory.ToString(), NoticeValue);
		}
	}
	// Interrupted (D110, D112, D113). The Live API gives no signal (the model stops by itself 1.2 to 2 s after the
	// visitor starts). The visitor wears a clip-on microphone: above InterruptLevel the sound is the visitor, below it
	// Frank's own voice from the speakers or nothing. A loud stretch that started while he speaks and lasted
	// InterruptMinSpeech s: his voice stops at the end of the word being heard, a short surprise with the head tilting
	// back a little, then his listening face. Not when he is nearly done (his newest words end his turn and are heard
	// within FinishedWithin s): then he finishes.
	const float Level = Live ? Live->VisitorLevel : 0.f;
	if (Level >= InterruptLevel)
	{
		LoudSince = LoudSince < 0.0 ? Now : LoudSince;
		LastLoud = Now;
	}
	else if (LoudSince >= 0.0 && Now - LastLoud > InterruptQuietGap)
	{
		LoudSince = -1.0;
	}
	if (LoudSince >= 0.0 && LoudSince != HandledOnset && Now - LoudSince >= InterruptMinSpeech)
	{
		HandledOnset = LoudSince;
		if (Live && Turns.bFrankVoice && LoudSince - Turns.FrankTurnStart >= InterruptInto && Now - LastInterruptAt > InterruptCooldown)
		{
			const float Left = Live->FrankWordsLeft();
			if (bLastFrankFinished && Left < FinishedWithin)
			{
				UE_LOG(LogMRLabBehavior, Log, TEXT("The visitor speaks as he finishes (%.1f s left): he finishes"), Left);
			}
			else
			{
				LastInterruptAt = Now;
				Session.Get()->StopAtWordEnd(); // Live is the same session, read-only here
				if (FCategory* Category = FindCategory(InterruptCategory))
				{
					Apply(*Category, InterruptValue);
				}
				Gaze.Interrupted(Now, HeadBackDegrees, InterruptLookSeconds);
				ListenAt = Now + ListenAfter;
				UE_LOG(LogMRLabBehavior, Log, TEXT("Interrupted: the visitor speaks over him (level %.3f, %.2f s after they started, %.1f s of his words left)"),
					Level, Now - LoudSince, Left);
			}
		}
	}
	if (ListenAt > 0.0 && Now >= ListenAt)
	{
		ListenAt = -1.0;
		if (FCategory* Category = FindCategory(ListenCategory))
		{
			Apply(*Category, ListenValue);
		}
	}
	if (Turns.State != LoggedTurn)
	{
		UE_LOG(LogMRLabBehavior, Log, TEXT("Turn: %s -> %s"), MRLabTurnName(LoggedTurn), MRLabTurnName(Turns.State));
		LoggedTurn = Turns.State;
	}
	UpdateBreath(Now, DeltaTime);

	OverrideCurves.Reset();
	BlinkCurves.Reset();
	USkeletalMeshComponent* Face = FaceMesh.Get();
	if (!Face || Face->GetBoneIndex(EyeBones[0]) == INDEX_NONE || Face->GetBoneIndex(EyeBones[1]) == INDEX_NONE)
	{
		return;
	}

	FMRLabGazeInput In;
	In.Now = Now;
	In.DeltaTime = DeltaTime;
	In.FrankForward = GetOwner()->GetActorRightVector().GetSafeNormal2D(); // his face looks along the actor's right vector
	In.FrankFeet = GetOwner()->GetActorLocation();
	In.Head = Face->GetSocketTransform(HeadBone);
	In.EyeL = Face->GetSocketLocation(EyeBones[0]);
	In.EyeR = Face->GetSocketLocation(EyeBones[1]);
	if (const AActor* Tracker = Ndc.Get())
	{
		const FBoolProperty* Tracked = FindFProperty<FBoolProperty>(Tracker->GetClass(), TEXT("bHeadTracked"));
		In.bTracked = Tracked && Tracked->GetPropertyValue_InContainer(Tracker) && Rig.IsValid();
		if (In.bTracked)
		{
			In.Visitor = Rig->GetComponentLocation();
		}
	}
	In.Turns = &Turns;
	In.Arousal = Arousal;
	In.Rapport = Rapport;
	In.HeadPitchOffset = Breath * BreathHeadDegrees; // the head goes up a little with the breath in (D114)
	Gaze.Update(In);

	TraceModelBlink = Live ? FMath::Max(Live->LipSyncCurves.FindRef(BlinkCurveNames[0]), Live->LipSyncCurves.FindRef(BlinkCurveNames[1])) : 0.f;
	Blinks.Update(Now, Turns, Gaze, TraceModelBlink, Arousal);

	const FVector Mid = (In.EyeL + In.EyeR) * 0.5;
	for (int32 Eye = 0; Eye < 2; ++Eye)
	{
		// The eye bone looks along its local Z (measured, README 4.10); the pose is the last evaluated one.
		const FTransform Bone = Face->GetSocketTransform(EyeBones[Eye]);
		const FVector Wanted = (Gaze.GazePoint - Bone.GetLocation()).GetSafeNormal();
		TraceEyeError[Eye] = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FVector::DotProduct(Bone.GetUnitAxis(EAxis::Z), Wanted), -1.f, 1.f)));
	}
	bTraceTracked = In.bTracked;
	TraceVisitorDistance = In.bTracked ? (In.Visitor - Mid).Size() : 0.f;
	TraceVisitorAngle = In.bTracked ? FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FVector::DotProduct(
		(Gaze.GazePoint - Mid).GetSafeNormal(), (In.Visitor - Mid).GetSafeNormal()), -1.f, 1.f))) : -1.f;

	if (PreviewControls.Num() > 0)
	{
		for (const TPair<FName, float>& Control : PreviewControls)
		{
			OverrideCurves.Emplace(Control.Key, Control.Value);
		}
	}
	else
	{
		for (int32 Eye = 0; Eye < 2; ++Eye)
		{
			for (int32 Curve = 0; Curve < 4; ++Curve)
			{
				OverrideCurves.Emplace(Gaze.Eyes[Eye].Curves[Curve], Gaze.Curves[Eye][Curve]);
			}
			BlinkCurves.Emplace(BlinkCurveNames[Eye], Blinks.Value);
		}
		// Head target into the body post-process AnimBP (its Look At nodes), before its animation update.
		USkeletalMeshComponent* Body = BodyMesh.Get();
		UAnimInstance* Post = Body ? Body->GetPostProcessInstance() : nullptr;
		const FStructProperty* Target = Post ? FindFProperty<FStructProperty>(Post->GetClass(), TEXT("HeadTarget")) : nullptr;
		if (Target && Target->Struct == TBaseStructure<FVector>::Get() && Gaze.bHeadValid)
		{
			*Target->ContainerPtrToValuePtr<FVector>(Post) = Gaze.HeadTarget;
		}
	}
	GazeCost += FPlatformTime::Seconds() - Now;
	++GazeTicks;
}

void UMRLabBehaviorComponent::UpdateBreath(double Now, float DeltaTime)
{
	// Breath in before he speaks (owner, D114); his voice is never held back for it. Cues: the visitor's turn ends
	// (visitor_yielding: his answer follows 0.7 to 1.8 s later), or the first text of a new utterance of his (in the
	// live test session only 0.04 to 0.3 s before his voice, so mostly too late on its own).
	const UMRLabLiveSession* Live = Session.Get();
	const double TextAt = Live ? Live->FrankUtteranceTextTime() : 0.0;
	const bool bVoice = Turns.bFrankVoice;
	const bool bNewText = TextAt > BreathTextSeen;
	const bool bYielded = Turns.State == EMRLabTurn::VisitorYielding && BreathTurn != EMRLabTurn::VisitorYielding;
	BreathTextSeen = FMath::Max(BreathTextSeen, TextAt);
	BreathTurn = Turns.State;
	if ((bNewText || bYielded) && !bVoice && (BreathPhase == EBreath::Rest || BreathPhase == EBreath::Out))
	{
		BreathPhase = EBreath::Waiting;
		BreathCue = Now;
		BreathWait = bYielded ? BreathYieldDelay : BreathDelay;
		UE_LOG(LogMRLabBehavior, Log, TEXT("Breath: cue, %s"), bYielded ? TEXT("the visitor's turn ended") : TEXT("his text arrived"));
	}
	// The visitor goes on talking instead: he lets the breath out.
	if ((BreathPhase == EBreath::Waiting || BreathPhase == EBreath::In) && !bVoice && Turns.State == EMRLabTurn::Listening)
	{
		UE_LOG(LogMRLabBehavior, Log, TEXT("Breath: let out, the visitor goes on (%.1f s after the cue)"), Now - BreathCue);
		BreathPhase = EBreath::Out;
		BreathPhaseAt = Now;
		BreathFrom = BreathRaw;
		BreathOutFor = FMath::Max(BreathOutRelease, 0.1f);
	}
	auto BreatheOut = [this, Now](float Seconds)
	{
		BreathPhase = EBreath::Out;
		BreathPhaseAt = Now;
		BreathFrom = BreathRaw;
		BreathOutFor = FMath::Max(Seconds, 0.1f);
	};
	switch (BreathPhase)
	{
	case EBreath::Waiting:
		BreathRaw = FMath::Max(0.f, BreathRaw - DeltaTime / FMath::Max(BreathOutRelease, 0.1f));
		if (bVoice)
		{
			BreathPhase = EBreath::Rest;
			UE_LOG(LogMRLabBehavior, Log, TEXT("Breath: no time to breathe in, his voice came %.2f s after the cue"), Now - BreathCue);
		}
		else if (Now - BreathCue >= BreathWait)
		{
			BreathPhase = EBreath::In;
			BreathPhaseAt = Now;
			BreathFrom = BreathRaw;
		}
		break;
	case EBreath::In:
		BreathRaw = FMath::Lerp(BreathFrom, 1.f, FMath::SmoothStep(0.f, BreathInSeconds, float(Now - BreathPhaseAt)));
		if (bVoice)
		{
			UE_LOG(LogMRLabBehavior, Log, TEXT("Breath: his voice %.2f s after the cue, %.2f s after the breath in started (%.0f %% in)"),
				Now - BreathCue, Now - BreathPhaseAt, BreathRaw * 100.f);
			BreatheOut(BreathOutSpeaking);
		}
		else if (Now - BreathPhaseAt > BreathInSeconds + BreathHoldMax)
		{
			UE_LOG(LogMRLabBehavior, Log, TEXT("Breath: let out, no voice %.1f s after the breath in"), Now - BreathPhaseAt);
			BreatheOut(BreathOutRelease);
		}
		break;
	case EBreath::Out:
		BreathRaw = FMath::Lerp(BreathFrom, 0.f, FMath::SmoothStep(0.f, BreathOutFor, float(Now - BreathPhaseAt)));
		if (Now - BreathPhaseAt >= BreathOutFor)
		{
			BreathPhase = EBreath::Rest;
		}
		break;
	default:
		BreathRaw = FMath::Max(0.f, BreathRaw - DeltaTime / FMath::Max(BreathOutRelease, 0.1f));
		break;
	}
	// A light critically damped smoothing (95 % after BreathSmoothSeconds), so a phase change never makes a kink.
	const float Goal = PreviewBreathLevel >= 0.f ? PreviewBreathLevel : BreathRaw;
	const float W = 7.75f / FMath::Max(BreathSmoothSeconds, 0.01f);
	const float Dt = FMath::Min(DeltaTime, 0.25f);
	const float D = Breath - Goal;
	const float C = BreathVel + W * D;
	const float E = FMath::Exp(-W * Dt);
	Breath = Goal + (D + C * Dt) * E;
	BreathVel = (BreathVel - W * C * Dt) * E;
}

void UMRLabBehaviorComponent::PreviewBreath(float Level)
{
	if (!bLoaded)
	{
		LoadSettings();
	}
	PreviewBreathLevel = FMath::Min(Level, 1.f);
	UE_LOG(LogMRLabBehavior, Log, TEXT("Preview breath %.2f"), PreviewBreathLevel);
}

void UMRLabBehaviorComponent::PreviewFaceControl(FName Control, float Value)
{
	if (Control.IsNone())
	{
		PreviewControls.Reset();
	}
	else
	{
		PreviewControls.Add(Control, FMath::Clamp(Value, 0.f, 1.f));
	}
	UE_LOG(LogMRLabBehavior, Log, TEXT("Preview control %s = %.2f (%d held)"), *Control.ToString(), Value, PreviewControls.Num());
}

float UMRLabBehaviorComponent::GroupWeight(FName Control, float Speaking) const
{
	const int32 Group = ControlGroup.FindRef(Control);
	return FMath::Lerp(1.f, SpeakingWeights[Group], FMath::Clamp(Speaking, 0.f, 1.f));
}

void UMRLabBehaviorComponent::UpdateFace(float Speaking)
{
	TMap<FName, float> Values;
	// A darker slow mood than his baseline deepens the persona face a little.
	const float BaselineScale = 1.f + 0.5f * FMath::Max(0.f, BaseValence - Valence);
	for (const TPair<FName, float>& Control : Baseline)
	{
		Values.FindOrAdd(Control.Key) += Control.Value * BaselineScale;
	}
	for (const FCategory& Category : Categories)
	{
		const float Weight = !PreviewCategory.IsNone()
			? (Category.Name == PreviewCategory ? PreviewActivation : 0.f)
			: Category.Shown;
		if (Weight <= 0.001f)
		{
			continue;
		}
		for (const TPair<FName, float>& Control : Category.Recipe)
		{
			Values.FindOrAdd(Control.Key) += Strength * Weight * Control.Value;
		}
	}
	FaceCurves.Reset(Values.Num());
	for (const TPair<FName, float>& Control : Values)
	{
		FaceCurves.Emplace(Control.Key, FMath::Clamp(Control.Value, 0.f, 1.f) * GroupWeight(Control.Key, Speaking));
	}
}

void UMRLabBehaviorComponent::PreviewExpression(FName Category, float Activation)
{
	if (!bLoaded && !LoadSettings())
	{
		return;
	}
	PreviewCategory = Category;
	PreviewActivation = FMath::Clamp(Activation, 0.f, 1.f);
	UpdateFace(0.f);
	UE_LOG(LogMRLabBehavior, Log, TEXT("Preview %s at %.2f: %d face controls"), *Category.ToString(), PreviewActivation, FaceCurves.Num());
}

void UMRLabBehaviorComponent::WriteTrace(float Speaking)
{
	if (!bTraceBehavior)
	{
		TraceFile.Reset();
		return;
	}
	const double Now = FPlatformTime::Seconds();
	if (!TraceFile.IsValid())
	{
		const FString Path = FPaths::ProjectSavedDir() / TEXT("Recordings") / (FDateTime::Now().ToString(TEXT("%Y%m%d-%H%M%S")) + TEXT("-behavior.jsonl"));
		TraceFile.Reset(IFileManager::Get().CreateFileWriter(*Path));
		TraceStart = Now;
		TraceNext = Now;
		UE_LOG(LogMRLabBehavior, Log, TEXT("Behaviour trace: %s"), *FPaths::ConvertRelativePathToFull(Path));
	}
	if (!TraceFile.IsValid() || Now < TraceNext)
	{
		return;
	}
	TraceNext += TraceInterval;
	const UMRLabLiveSession* Live = Session.Get();
	FString Line = FString::Printf(TEXT("{\"t\":%.3f,\"speaking\":%.3f,\"playhead\":%lld,\"waiting\":%.3f,\"valence\":%.3f,\"arousal\":%.3f,\"rapport\":%.3f,\"mood\":%d,"),
		Now - TraceStart, Speaking, Live ? Live->VoicePlayhead() : 0LL, Live ? Live->VoiceWaiting() : 0.f, Valence, Arousal, Rapport, CurrentMood);
	Line += FString::Printf(TEXT("\"turn\":\"%s\",\"vlevel\":%.4f,\"gaze\":\"%s\",\"tracked\":%d,\"vdist\":%.0f,\"vangle\":%.2f,\"eyes\":[[%.2f,%.2f],[%.2f,%.2f]],")
		TEXT("\"curves\":[[%.3f,%.3f,%.3f,%.3f],[%.3f,%.3f,%.3f,%.3f]],\"shift\":[%.3f,%.1f],\"blink\":%.3f,\"mblink\":%.3f,\"head\":[%.1f,%.1f,%.1f],\"eyeerr\":[%.2f,%.2f],\"blinks\":[%d,%d],\"shown\":{"),
		MRLabTurnName(Turns.State), Live ? Live->VisitorLevel : 0.f, GazeKindName(Gaze.Kind), bTraceTracked ? 1 : 0, TraceVisitorDistance, TraceVisitorAngle,
		Gaze.YawPitch[0][0], Gaze.YawPitch[0][1], Gaze.YawPitch[1][0], Gaze.YawPitch[1][1],
		Gaze.Curves[0][0], Gaze.Curves[0][1], Gaze.Curves[0][2], Gaze.Curves[0][3], Gaze.Curves[1][0], Gaze.Curves[1][1], Gaze.Curves[1][2], Gaze.Curves[1][3],
		Gaze.LastShiftAt - TraceStart, Gaze.LastShiftDegrees, Blinks.Value, TraceModelBlink, Gaze.HeadTarget.X, Gaze.HeadTarget.Y, Gaze.HeadTarget.Z,
		TraceEyeError[0], TraceEyeError[1], Blinks.OwnCount, Blinks.ModelCount);
	// The jaw as the face gets it (lip sync plus the expression layer, README 4.11) and the breath (D114).
	static const FName JawOpen(TEXT("CTRL_expressions_jawOpen"));
	float LayerJaw = 0.f;
	for (const TPair<FName, float>& Control : FaceCurves)
	{
		LayerJaw += Control.Key == JawOpen ? Control.Value : 0.f;
	}
	Line.InsertAt(Line.Len() - FCString::Strlen(TEXT("\"shown\":{")), FString::Printf(TEXT("\"jaw\":%.3f,\"breath\":%.3f,"),
		FMath::Clamp((Live ? Live->LipSyncCurves.FindRef(JawOpen) : 0.f) + LayerJaw, 0.f, 1.f), Breath));
	bool bFirst = true;
	for (const FCategory& Category : Categories)
	{
		Line += FString::Printf(TEXT("%s\"%s\":[%.3f,%.3f]"), bFirst ? TEXT("") : TEXT(","), *Category.Name.ToString(), Category.Activation,
			Category.Shown);
		bFirst = false;
	}
	Line += TEXT("},\"face\":{");
	bFirst = true;
	for (const TPair<FName, float>& Control : FaceCurves)
	{
		Line += FString::Printf(TEXT("%s\"%s\":%.3f"), bFirst ? TEXT("") : TEXT(","), *Control.Key.ToString(), Control.Value);
		bFirst = false;
	}
	Line += TEXT("}}\n");
	const FTCHARToUTF8 Utf8(*Line);
	TraceFile->Serialize((void*)Utf8.Get(), Utf8.Length());
}
