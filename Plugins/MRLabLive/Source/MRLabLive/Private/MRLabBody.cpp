#include "MRLabBody.h"

namespace MRLabBodyLocal
{
	float Num(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field, float Default)
	{
		double Value = Default;
		return Object.IsValid() && Object->TryGetNumberField(Field, Value) ? float(Value) : Default;
	}

	// One step of two critically damped stages in series towards Goal (95 % after Seconds): eased in and out, as the head.
	void Spring2(float& A, float& AVel, float& X, float& XVel, float Goal, float Seconds, float DeltaTime)
	{
		const float W = 7.75f / FMath::Max(Seconds, 0.05f);
		const float Dt = FMath::Min(DeltaTime, 0.25f);
		auto Stage = [W, Dt](float& Value, float& Vel, float Target)
		{
			const float D = Value - Target;
			const float C = Vel + W * D;
			const float E = FMath::Exp(-W * Dt);
			Value = Target + (D + C * Dt) * E;
			Vel = (Vel - W * C * Dt) * E;
		};
		Stage(A, AVel, Goal);
		Stage(X, XVel, A);
	}
}

// --- Posture ---

void FMRLabPosture::Load(const TSharedPtr<FJsonObject>& Object)
{
	using namespace MRLabBodyLocal;
	if (Object.IsValid())
	{
		Object->TryGetStringField(TEXT("body_anim"), BodyAnim);
	}
	ChestShare = Num(Object, TEXT("chest_share"), ChestShare);
	ChestMax = Num(Object, TEXT("chest_max"), ChestMax);
	ListenLean = Num(Object, TEXT("listen_lean"), ListenLean);
	Seconds = Num(Object, TEXT("seconds"), Seconds);
	LowerPerValence = Num(Object, TEXT("lower_per_valence"), LowerPerValence);
	LowerMax = Num(Object, TEXT("lower_max"), LowerMax);
}

void FMRLabPosture::Update(float DeltaTime, EMRLabTurn State, float VisitorYaw, float ValenceDrop)
{
	const bool bConversation = State != EMRLabTurn::Outside && State != EMRLabTurn::Pause;
	const bool bListening = State == EMRLabTurn::Listening || State == EMRLabTurn::VisitorYielding;
	const float YawGoal = bConversation ? FMath::Clamp(ChestShare * VisitorYaw, -ChestMax, ChestMax) : 0.f;
	const float LeanGoal = bListening ? ListenLean : 0.f;
	const float LowerGoal = FMath::Clamp(LowerPerValence * ValenceDrop, 0.f, LowerMax);
	MRLabBodyLocal::Spring2(YawA, YawVA, ChestYaw, YawV, YawGoal, Seconds, DeltaTime);
	MRLabBodyLocal::Spring2(LeanA, LeanVA, Lean, LeanV, LeanGoal, Seconds, DeltaTime);
	MRLabBodyLocal::Spring2(LowerA, LowerVA, Lower, LowerV, LowerGoal, Seconds, DeltaTime);
}

// --- Nods while he speaks ---

void FMRLabNods::Load(const TSharedPtr<FJsonObject>& Object)
{
	using namespace MRLabBodyLocal;
	Lead = Num(Object, TEXT("lead"), Lead);
	Down = Num(Object, TEXT("down"), Down);
	Up = Num(Object, TEXT("up"), Up);
	MinGap = Num(Object, TEXT("min_gap"), MinGap);
	Peak = Num(Object, TEXT("peak"), Peak);
	MinLevel = Num(Object, TEXT("min_level"), MinLevel);
	MeanSeconds = Num(Object, TEXT("mean_seconds"), MeanSeconds);
	Base = Num(Object, TEXT("base"), Base);
	Top = Num(Object, TEXT("top"), Top);
	EmphasisTop = Num(Object, TEXT("emphasis_top"), EmphasisTop);
	ArousalGain = Num(Object, TEXT("arousal_gain"), ArousalGain);
}

void FMRLabNods::Update(double Now, float DeltaTime, float Level, bool bHeard, float Emphasis, float ArousalUp)
{
	// Running mean of his loudness while he speaks.
	if (Level > MinLevel * 0.5f)
	{
		Mean += (Level - Mean) * (1.f - FMath::Exp(-DeltaTime / FMath::Max(MeanSeconds, 0.1f)));
	}
	// The previous level was a peak: it is heard about Lead s after it was read, which is when the nod is lowest, so
	// the nod starts Down s before that.
	const float Candidate = Prev[0];
	const bool bPeak = Candidate > Prev[1] && Candidate >= Level && Candidate >= MinLevel && Candidate >= Peak * Mean;
	if (bPeak && bHeard && Now - LastStart >= MinGap)
	{
		const float Excess = FMath::Clamp((Candidate / FMath::Max(Peak * Mean, 1e-4f) - 1.f), 0.f, 1.f);
		const float Size = FMath::Lerp(FMath::Lerp(Base, Top, Excess), EmphasisTop, FMath::Clamp(Emphasis, 0.f, 1.f));
		Amplitude = Size * (1.f + ArousalGain * FMath::Clamp(ArousalUp, 0.f, 1.f));
		Start = Now + FMath::Max(0.f, Lead - DeltaTime - Down);
		LastStart = Start;
		++Count;
	}
	Prev[1] = Prev[0];
	Prev[0] = Level;

	// Shape: eased down, eased back up.
	const float T = float(Now - Start);
	if (T < 0.f || T > Down + Up)
	{
		Pitch = 0.f;
	}
	else
	{
		const float X = T < Down ? T / Down : 1.f - (T - Down) / Up;
		Pitch = Amplitude * FMath::SmoothStep(0.f, 1.f, X);
	}
}
