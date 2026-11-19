#include "AnimNode_MRLabLife.h"

#include "Animation/AnimInstance.h"

DEFINE_LOG_CATEGORY_STATIC(LogMRLabLife, Log, All);

void FAnimNode_MRLabLife::Initialize_AnyThread(const FAnimationInitializeContext& Context)
{
	FAnimNode_Base::Initialize_AnyThread(Context);
	Source.Initialize(Context);
}

void FAnimNode_MRLabLife::CacheBones_AnyThread(const FAnimationCacheBonesContext& Context)
{
	Source.CacheBones(Context);
}

void FAnimNode_MRLabLife::Update_AnyThread(const FAnimationUpdateContext& Context)
{
	Source.Update(Context);
}

void FAnimNode_MRLabLife::Evaluate_AnyThread(FPoseContext& Output)
{
	Source.Evaluate(Output);
}

void FAnimNode_MRLabLife::PreUpdate(const UAnimInstance* InAnimInstance)
{
	if (!bReported)
	{
		bReported = true;
		const AActor* Owner = InAnimInstance ? InAnimInstance->GetOwningActor() : nullptr;
		UE_LOG(LogMRLabLife, Log, TEXT("MRLab Life node running on %s (PreUpdate on the game thread: %s)"),
			Owner ? *Owner->GetName() : TEXT("no actor"), IsInGameThread() ? TEXT("yes") : TEXT("no"));
	}
}
