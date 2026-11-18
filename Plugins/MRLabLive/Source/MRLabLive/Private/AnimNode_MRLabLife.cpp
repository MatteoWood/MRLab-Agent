#include "AnimNode_MRLabLife.h"

#include "Animation/AnimInstance.h"
#include "Animation/AnimInstanceProxy.h"
#include "GameFramework/Actor.h"
#include "MRLabBehaviorComponent.h"

void FAnimNode_MRLabLife::Initialize_AnyThread(const FAnimationInitializeContext& Context)
{
	FAnimNode_Base::Initialize_AnyThread(Context);
	Source.Initialize(Context);
}

void FAnimNode_MRLabLife::CacheBones_AnyThread(const FAnimationCacheBonesContext& Context)
{
	Source.CacheBones(Context);
	const FBoneContainer& Bones = Context.AnimInstanceProxy->GetRequiredBones();
	for (FBoneReference& Bone : Spine)
	{
		Bone.Initialize(Bones);
	}
	for (FBoneReference& Bone : Clavicle)
	{
		Bone.Initialize(Bones);
	}
	for (FBoneReference& Bone : UpperArm)
	{
		Bone.Initialize(Bones);
	}
}

void FAnimNode_MRLabLife::Update_AnyThread(const FAnimationUpdateContext& Context)
{
	Source.Update(Context);
}

void FAnimNode_MRLabLife::Evaluate_AnyThread(FPoseContext& Output)
{
	Source.Evaluate(Output);
	if (ChestDegrees == 0.f && ChestLift == 0.f && ShoulderDegrees == 0.f)
	{
		return;
	}
	const FBoneContainer& Bones = Output.AnimInstanceProxy->GetRequiredBones();
	FCompactPose& Pose = Output.Pose;
	auto ParentRotation = [&Pose](FCompactPoseBoneIndex Index) // the parent's rotation in the component
	{
		FQuat Parent = FQuat::Identity;
		for (FCompactPoseBoneIndex Up = Pose.GetParentBoneIndex(Index); Up.IsValid(); Up = Pose.GetParentBoneIndex(Up))
		{
			Parent = Pose[Up].GetRotation() * Parent;
		}
		return Parent;
	};
	// Turns a bone about an axis of the component, at the bone; its children follow.
	auto Turn = [&Bones, &Pose, &ParentRotation](const FBoneReference& Bone, const FVector& Axis, float Degrees)
	{
		if (Degrees == 0.f || !Bone.IsValidToEvaluate(Bones))
		{
			return;
		}
		const FCompactPoseBoneIndex Index = Bone.GetCompactPoseIndex(Bones);
		const FQuat Parent = ParentRotation(Index);
		const FQuat Rotation(Axis, FMath::DegreesToRadians(Degrees));
		FTransform& Local = Pose[Index];
		Local.SetRotation((Parent.Inverse() * Rotation * Parent * Local.GetRotation()).GetNormalized());
	};
	// Moves a bone by an offset in the component; its children follow.
	auto Move = [&Bones, &Pose, &ParentRotation](const FBoneReference& Bone, const FVector& Offset)
	{
		if (Offset.IsZero() || !Bone.IsValidToEvaluate(Bones))
		{
			return;
		}
		const FCompactPoseBoneIndex Index = Bone.GetCompactPoseIndex(Bones);
		Pose[Index].AddToTranslation(ParentRotation(Index).Inverse().RotateVector(Offset));
	};
	// The MetaHuman body's component space (measured on the reference pose): X his left, Y forward, Z up. A positive
	// turn about X takes the top of the spine back (it extends a little); the chest (spine_05, with neck, head and arms)
	// rises and comes forward by half as much; about Y a positive turn lifts the right clavicle and lowers the left one.
	// The upper arms turn back by the same angle, so the arms keep hanging as they did and only rise with the shoulders
	// (turned with the clavicles, the hands swung out by 1 cm).
	static constexpr float SpineShare[3] = { 0.3f, 0.35f, 0.35f };
	for (int32 Index = 0; Index < 3; ++Index)
	{
		Turn(Spine[Index], FVector::XAxisVector, ChestDegrees * SpineShare[Index]);
	}
	Move(Spine[2], FVector(0.f, 0.5f, 1.f) * ChestLift);
	Turn(Clavicle[0], FVector::YAxisVector, -ShoulderDegrees);
	Turn(Clavicle[1], FVector::YAxisVector, ShoulderDegrees);
	Turn(UpperArm[0], FVector::YAxisVector, ShoulderDegrees);
	Turn(UpperArm[1], FVector::YAxisVector, -ShoulderDegrees);
}

void FAnimNode_MRLabLife::PreUpdate(const UAnimInstance* InAnimInstance)
{
	const AActor* Owner = InAnimInstance ? InAnimInstance->GetOwningActor() : nullptr;
	if (Owner && (!bSearched || !Behavior.IsValid()))
	{
		// Components can be created after the AnimBP starts (construction script, Play), so look again until found.
		Behavior = Owner->FindComponentByClass<UMRLabBehaviorComponent>();
		bSearched = true;
	}
	const UMRLabBehaviorComponent* Layer = Behavior.Get();
	const float Breath = Layer ? Layer->GetBreath() : 0.f;
	ChestDegrees = Layer ? Breath * Layer->GetBreathChestDegrees() : 0.f;
	ChestLift = Layer ? Breath * Layer->GetBreathChestLift() : 0.f;
	ShoulderDegrees = Layer ? Breath * Layer->GetBreathShoulderDegrees() : 0.f;
}
