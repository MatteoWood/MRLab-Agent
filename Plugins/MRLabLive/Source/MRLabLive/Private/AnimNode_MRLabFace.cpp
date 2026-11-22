#include "AnimNode_MRLabFace.h"

#include "Animation/AnimCurveTypes.h"
#include "Animation/AnimInstance.h"
#include "GameFramework/Actor.h"
#include "MRLabBehaviorComponent.h"
#include "MRLabLiveSession.h"

void FAnimNode_MRLabFace::Initialize_AnyThread(const FAnimationInitializeContext& Context)
{
	FAnimNode_Base::Initialize_AnyThread(Context);
	Source.Initialize(Context);
}

void FAnimNode_MRLabFace::CacheBones_AnyThread(const FAnimationCacheBonesContext& Context)
{
	Source.CacheBones(Context);
}

void FAnimNode_MRLabFace::Update_AnyThread(const FAnimationUpdateContext& Context)
{
	Source.Update(Context);
}

void FAnimNode_MRLabFace::PreUpdate(const UAnimInstance* InAnimInstance)
{
	const AActor* Owner = InAnimInstance ? InAnimInstance->GetOwningActor() : nullptr;
	if (Owner && (!bSearched || (!Session.IsValid() && !Behavior.IsValid())))
	{
		// Components can be created after the AnimBP starts (construction script, Play), so look again until found.
		Session = Owner->FindComponentByClass<UMRLabLiveSession>();
		Behavior = Owner->FindComponentByClass<UMRLabBehaviorComponent>();
		bSearched = true;
	}

	// Lip sync as solved for the sample heard now; the expression layer added on top, clamped (README 4.14); the eye
	// look curves replace the lip sync's (they are 0 there), and so do the blinks, which include the model's (README 4.10).
	TMap<FName, float> Merged;
	if (const UMRLabLiveSession* Live = Session.Get())
	{
		Merged = Live->LipSyncCurves;
	}
	if (const UMRLabBehaviorComponent* Layer = Behavior.Get())
	{
		for (const TPair<FName, float>& Control : Layer->GetFaceCurves())
		{
			float& Value = Merged.FindOrAdd(Control.Key);
			Value = FMath::Clamp(Value + Control.Value, 0.f, 1.f);
		}
		for (const TPair<FName, float>& Control : Layer->GetOverrideCurves())
		{
			Merged.Add(Control.Key, FMath::Clamp(Control.Value, 0.f, 1.f));
		}
	}
	Curves = Merged.Array();
}

void FAnimNode_MRLabFace::Evaluate_AnyThread(FPoseContext& Output)
{
	Source.Evaluate(Output);
	if (Curves.IsEmpty())
	{
		return;
	}
	FBlendedCurve Curve;
	Curve.Reserve(Curves.Num());
	for (const TPair<FName, float>& Control : Curves)
	{
		Curve.Add(Control.Key, Control.Value);
	}
	// Override, as the Modify Curve node (Blend, alpha 1) did before.
	UE::Anim::FNamedValueArrayUtils::Union(Output.Curve, Curve,
		[](UE::Anim::FCurveElement& InOutResult, const UE::Anim::FCurveElement& InCurveElement, UE::Anim::ENamedValueUnionFlags InFlags)
		{
			if (EnumHasAnyFlags(InFlags, UE::Anim::ENamedValueUnionFlags::ValidArg1))
			{
				InOutResult.Value = InCurveElement.Value;
			}
		});
}
