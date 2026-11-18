#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNodeBase.h"
#include "BoneContainer.h"
#include "AnimNode_MRLabLife.generated.h"

class UMRLabBehaviorComponent;

/**
 * Frank's procedural body layer (README 4.10, Step 9D). So far: the breath in before he speaks (D114), from the MRLab
 * behaviour component on the owning actor: the upper spine extends a little and the shoulders rise. Place it on the
 * local pose before the head's Look At nodes. The values are gathered in PreUpdate on the game thread, so the AnimBP
 * can update on worker threads.
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
	TWeakObjectPtr<UMRLabBehaviorComponent> Behavior;
	bool bSearched = false;
	// Written in PreUpdate, read in Evaluate_AnyThread: degrees and centimetres for this frame.
	float ChestDegrees = 0.f;
	float ChestLift = 0.f;
	float ShoulderDegrees = 0.f;
	FBoneReference Spine[3] = { FBoneReference(TEXT("spine_03")), FBoneReference(TEXT("spine_04")), FBoneReference(TEXT("spine_05")) };
	FBoneReference Clavicle[2] = { FBoneReference(TEXT("clavicle_l")), FBoneReference(TEXT("clavicle_r")) };
	FBoneReference UpperArm[2] = { FBoneReference(TEXT("upperarm_l")), FBoneReference(TEXT("upperarm_r")) };
};
