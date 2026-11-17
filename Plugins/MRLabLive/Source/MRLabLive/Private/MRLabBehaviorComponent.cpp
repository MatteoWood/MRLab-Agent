#include "MRLabBehaviorComponent.h"

#include "Dom/JsonObject.h"
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

	float NumberOr(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field, float Default)
	{
		double Value = Default;
		return Object.IsValid() && Object->TryGetNumberField(Field, Value) ? float(Value) : Default;
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
}

void UMRLabBehaviorComponent::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UMRLabLiveSession* Live = Session.Get())
	{
		Live->OnDecision.Remove(DecisionHandle);
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
	if (!Delivery)
	{
		return;
	}
	const float Probability = Delivery->Probability(Delivery->Choice);
	if (Probability < MinProbability || Delivery->Confidence < MinConfidence)
	{
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
	if (Item.Mood >= 0 || !Item.Category.IsNone())
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
		if (Item.Mood >= 0 && (Item.Mood != CurrentMood || !FMath::IsNearlyEqual(Item.Intensity, CurrentIntensity)))
		{
			Live->SetLipSyncMood(Item.Mood, Item.Intensity);
			CurrentMood = Item.Mood;
			CurrentIntensity = Item.Intensity;
			UE_LOG(LogMRLabBehavior, Log, TEXT("Lip sync mood %d (%.2f) at voice sample %lld, playhead %lld (%.2f s after the text): \"%s\""),
				Item.Mood, Item.Intensity, Sample, Playhead, Now - Item.Created, *Item.Text);
		}
		if (FCategory* Category = FindCategory(Item.Category))
		{
			Apply(*Category, Item.Value * Category->Gain);
		}
		Scheduled.RemoveAt(Index);
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
		return;
	}

	RunScheduled();
	const double Now = FPlatformTime::Seconds();

	// Back to the voice's own mood after he has been silent for a while.
	if (Speaking > 0.05f)
	{
		SilentSince = Now;
	}
	else if (CurrentMood != AutomaticMood && Now - SilentSince > MoodReleaseSeconds)
	{
		if (UMRLabLiveSession* Writable = Session.Get())
		{
			Writable->SetLipSyncMood(AutomaticMood, 0.f);
		}
		CurrentMood = AutomaticMood;
		CurrentIntensity = 0.f;
	}

	for (FCategory& Category : Categories)
	{
		if (Now > Category.HoldUntil)
		{
			Category.Activation = Ease(Category.Activation, 0.f, FallSeconds, DeltaTime);
		}
		const bool bRising = Category.Activation > Category.Shown;
		Category.Shown = Ease(Category.Shown, Category.Activation, bRising ? (Category.Flash > 0.f ? FlashSeconds : RiseSeconds) : FallSeconds, DeltaTime);
		Category.FlashLevel = Ease(Category.FlashLevel, 0.f, FlashSeconds * 2.f, DeltaTime);
	}
	const float Return = 1.f - FMath::Exp(-DeltaTime / FMath::Max(ReturnSeconds, 1.f));
	Valence += (BaseValence - Valence) * Return;
	Arousal += (BaseArousal - Arousal) * Return;

	UpdateFace(Speaking);
	WriteTrace(Speaking);
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
			: FMath::Min(1.f, Category.Shown + Category.FlashLevel);
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
	FString Line = FString::Printf(TEXT("{\"t\":%.3f,\"speaking\":%.3f,\"playhead\":%lld,\"valence\":%.3f,\"arousal\":%.3f,\"rapport\":%.3f,\"mood\":%d,\"shown\":{"),
		Now - TraceStart, Speaking, Live ? Live->VoicePlayhead() : 0LL, Valence, Arousal, Rapport, CurrentMood);
	bool bFirst = true;
	for (const FCategory& Category : Categories)
	{
		Line += FString::Printf(TEXT("%s\"%s\":[%.3f,%.3f]"), bFirst ? TEXT("") : TEXT(","), *Category.Name.ToString(), Category.Activation,
			FMath::Min(1.f, Category.Shown + Category.FlashLevel));
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
