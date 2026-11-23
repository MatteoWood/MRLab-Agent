#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNodeBase.h"
#include "BoneContainer.h"
#include "AnimNode_MRLabLife.generated.h"

class UMRLabBehaviorComponent;

/**
 * Frank's procedural body layer (README 4.15, Step 9D): the chest posture of the behaviour component on the owning
 * actor (turned towards the visitor, leaning, lowered by a low mood) added to the input pose on the five spine bones
 * only, spread from the lowest to the highest; pelvis and legs stay as they come, so the feet do not slide.
 * It reads the game thread state in PreUpdate, which lets the AnimBP update on worker threads.
 */
USTRUCT(BlueprintInternalUseOnly)
struct MRLABLIVE_API FAnimNode_MRLabLife : public FAnimNode_Base
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
	static constexpr int32 SpineCount = 5;
	FBoneReference Spine[SpineCount];
	TWeakObjectPtr<const UMRLabBehaviorComponent> Behavior;
	bool bSearched = false;
	bool bReported = false;
	FQuat ChestDelta = FQuat::Identity; // whole chest rotation in component space, written in PreUpdate
};
