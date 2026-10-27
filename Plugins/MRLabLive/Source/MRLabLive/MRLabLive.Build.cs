using UnrealBuildTool;

public class MRLabLive : ModuleRules
{
	public MRLabLive(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "AudioMixer", "AudioPlatformConfiguration" });
		PrivateDependencyModuleNames.AddRange(new string[] { "AudioCapture", "AudioMixerCore", "Json" });
		PublicSystemLibraries.Add("winhttp.lib");
	}
}
