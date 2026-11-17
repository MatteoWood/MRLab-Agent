using UnrealBuildTool;

// Editor classes of MRLabLive's animation nodes. UncookedOnly: loaded in the editor and in nDisplay nodes started
// from the editor (UnrealEditor.exe -game), as the engine's own animation node modules.
public class MRLabLiveUncooked : ModuleRules
{
	public MRLabLiveUncooked(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PrivateDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine", "MRLabLive" });
		if (Target.bBuildEditor)
		{
			PrivateDependencyModuleNames.AddRange(new[] { "AnimGraph", "BlueprintGraph", "UnrealEd" });
		}
	}
}
