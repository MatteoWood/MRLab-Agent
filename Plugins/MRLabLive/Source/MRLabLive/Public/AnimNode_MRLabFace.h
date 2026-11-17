#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNodeBase.h"
#include "AnimNode_MRLabFace.generated.h"

class UMRLabBehaviorComponent;
class UMRLabLiveSession;

/**
 * Frank's face controls (README 4.14): the lip sync of the MRLab Live session plus the expression layer of the MRLab
 * behaviour component on the owning actor, merged and written as CTRL_expressions_* curves. Place it before RigLogic.
 * The values are gathered in PreUpdate on the game thread, so the AnimBP can update on worker threads.
 */
USTRUCT(BlueprintInternalUseOnly)
struct MRLABLIVE_API FAnimNode_MRLabFace : public FAnimNode_Base
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, Category = Links)
	FPoseLink Source;

	virtual void Initialize_AnyThread(const FAnimationInitializeContext& Context) override;
	virtual void CacheBones_AnyThread(const FAnimationCacheBonesContext& Context) override;
	virtual void Update_AnyThread(const FAnimationUpdateContext& Context) override;
	virtual void Evaluate_AnyThread(FPoseContext& Output) override;
	virtual bool HasPreUpdate() const override { return true; }
	virtual void PreUpdate(const UAnimInstance* InAnimInstance) override;

private:
	TWeakObjectPtr<UMRLabLiveSession> Session;
	TWeakObjectPtr<UMRLabBehaviorComponent> Behavior;
	bool bSearched = false;
	TArray<TPair<FName, float>> Curves; // written in PreUpdate, read in Evaluate_AnyThread
};
