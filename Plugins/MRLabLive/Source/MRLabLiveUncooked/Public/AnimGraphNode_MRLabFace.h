#pragma once

#include "CoreMinimal.h"
#include "AnimGraphNode_Base.h"
#include "AnimNode_MRLabFace.h"
#include "AnimGraphNode_MRLabFace.generated.h"

/** Graph node of FAnimNode_MRLabFace (Frank's lip sync and expressions as face controls). */
UCLASS()
class UAnimGraphNode_MRLabFace : public UAnimGraphNode_Base
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, Category = Settings)
	FAnimNode_MRLabFace Node;

	virtual FText GetNodeTitle(ENodeTitleType::Type TitleType) const override { return INVTEXT("MRLab Face"); }
	virtual FText GetTooltipText() const override { return INVTEXT("Frank's lip sync and expression layer, written as CTRL_expressions_* curves. Place before RigLogic."); }
	virtual FText GetMenuCategory() const override { return INVTEXT("MRLab"); }
};
