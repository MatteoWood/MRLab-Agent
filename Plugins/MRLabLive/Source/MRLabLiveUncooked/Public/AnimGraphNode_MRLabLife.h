#pragma once

#include "CoreMinimal.h"
#include "AnimGraphNode_Base.h"
#include "AnimNode_MRLabLife.h"
#include "AnimGraphNode_MRLabLife.generated.h"

/** Graph node of FAnimNode_MRLabLife (Frank's procedural body layer). */
UCLASS()
class UAnimGraphNode_MRLabLife : public UAnimGraphNode_Base
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, Category = Settings)
	FAnimNode_MRLabLife Node;

	virtual FText GetNodeTitle(ENodeTitleType::Type TitleType) const override { return INVTEXT("MRLab Life"); }
	virtual FText GetTooltipText() const override { return INVTEXT("Frank's procedural body layer (breath, sway, nods, posture)."); }
	virtual FText GetMenuCategory() const override { return INVTEXT("MRLab"); }
};
