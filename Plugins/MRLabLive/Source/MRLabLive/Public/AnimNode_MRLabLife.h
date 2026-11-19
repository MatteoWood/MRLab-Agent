#pragma once

#include "CoreMinimal.h"
#include "Animation/AnimNodeBase.h"
#include "AnimNode_MRLabLife.generated.h"

/**
 * Frank's procedural body layer (README section 5, Step 9D). For now it passes its input pose through and checks the
 * plumbing: it reads the game thread state in PreUpdate, which lets the AnimBP update on worker threads.
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
	bool bReported = false;
};
