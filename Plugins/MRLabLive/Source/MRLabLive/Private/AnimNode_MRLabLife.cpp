#include "AnimNode_MRLabLife.h"

#include "Animation/AnimInstance.h"
#include "Animation/AnimInstanceProxy.h"
#include "Components/SkeletalMeshComponent.h"
#include "MRLabBehaviorComponent.h"

DEFINE_LOG_CATEGORY_STATIC(LogMRLabLife, Log, All);

namespace
{
	// MetaHuman body spine, lowest first; each is the parent of the next. Shares of the whole chest rotation (sum 1).
	const TCHAR* SpineNames[] = { TEXT("spine_01"), TEXT("spine_02"), TEXT("spine_03"), TEXT("spine_04"), TEXT("spine_05") };
	constexpr float SpineShares[] = { 0.1f, 0.15f, 0.2f, 0.25f, 0.3f };
}

void FAnimNode_MRLabLife::Initialize_AnyThread(const FAnimationInitializeContext& Context)
{
	FAnimNode_Base::Initialize_AnyThread(Context);
	Source.Initialize(Context);
}

void FAnimNode_MRLabLife::CacheBones_AnyThread(const FAnimationCacheBonesContext& Context)
{
	Source.CacheBones(Context);
	const FBoneContainer& Required = Context.AnimInstanceProxy->GetRequiredBones();
	for (int32 Index = 0; Index < SpineCount; ++Index)
	{
		Spine[Index].BoneName = SpineNames[Index];
		Spine[Index].Initialize(Required);
	}
}

void FAnimNode_MRLabLife::Update_AnyThread(const FAnimationUpdateContext& Context)
{
	Source.Update(Context);
}

void FAnimNode_MRLabLife::Evaluate_AnyThread(FPoseContext& Output)
{
	Source.Evaluate(Output);
	if (ChestDelta.Equals(FQuat::Identity, 1e-6f))
	{
		return;
	}
	FCompactPose& Pose = Output.Pose;
	const FBoneContainer& Required = Pose.GetBoneContainer();
	const FCompactPoseBoneIndex First = Spine[0].GetCompactPoseIndex(Required);
	if (First == INDEX_NONE)
	{
		return;
	}
	// Component space rotation of the first spine bone's parent (the pelvis).
	FQuat ParentCS = FQuat::Identity;
	for (FCompactPoseBoneIndex Bone = Pose.GetParentBoneIndex(First); Bone != INDEX_NONE; Bone = Pose.GetParentBoneIndex(Bone))
	{
		ParentCS = Pose[Bone].GetRotation() * ParentCS;
	}
	// Each bone turns by its share of the chest rotation about the component axes; its children follow.
	for (int32 Index = 0; Index < SpineCount; ++Index)
	{
		const FCompactPoseBoneIndex Bone = Spine[Index].GetCompactPoseIndex(Required);
		if (Bone == INDEX_NONE)
		{
			return;
		}
		const FQuat Share = FQuat::Slerp(FQuat::Identity, ChestDelta, SpineShares[Index]);
		const FQuat Local = Pose[Bone].GetRotation();
		const FQuat NewLocal = (ParentCS.Inverse() * Share * ParentCS * Local).GetNormalized();
		Pose[Bone].SetRotation(NewLocal);
		ParentCS = ParentCS * NewLocal;
	}
}

void FAnimNode_MRLabLife::PreUpdate(const UAnimInstance* InAnimInstance)
{
	const AActor* Owner = InAnimInstance ? InAnimInstance->GetOwningActor() : nullptr;
	if (Owner && (!bSearched || !Behavior.IsValid()))
	{
		bSearched = true;
		Behavior = Owner->FindComponentByClass<UMRLabBehaviorComponent>();
	}
	if (!bReported)
	{
		bReported = true;
		UE_LOG(LogMRLabLife, Log, TEXT("MRLab Life node running on %s (PreUpdate on the game thread: %s, behaviour component %s)"),
			Owner ? *Owner->GetName() : TEXT("no actor"), IsInGameThread() ? TEXT("yes") : TEXT("no"),
			Behavior.IsValid() ? TEXT("found") : TEXT("missing"));
	}
	const UMRLabBehaviorComponent* Body = Behavior.Get();
	const USkeletalMeshComponent* Mesh = InAnimInstance ? InAnimInstance->GetSkelMeshComponent() : nullptr;
	if (!Body || !Mesh)
	{
		ChestDelta = FQuat::Identity;
		return;
	}
	float Yaw = 0.f;
	float Tilt = 0.f;
	FVector Forward = FVector::ForwardVector;
	Body->GetPosture(Yaw, Tilt, Forward);
	// World rotation: turn about the vertical, then tip the chest towards the direction he faces. Into component space.
	const FVector Up = FVector::UpVector;
	const float TiltRad = FMath::DegreesToRadians(Tilt);
	const FQuat Tip = FQuat::FindBetweenNormals(Up, (Up * FMath::Cos(TiltRad) + Forward.GetSafeNormal2D() * FMath::Sin(TiltRad)).GetSafeNormal());
	const FQuat World = FRotator(0.f, Yaw, 0.f).Quaternion() * Tip;
	const FQuat Component = Mesh->GetComponentTransform().GetRotation();
	ChestDelta = (Component.Inverse() * World * Component).GetNormalized();
}
