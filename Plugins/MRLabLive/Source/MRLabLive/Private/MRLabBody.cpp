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

// --- Listening nods (9E) ---

void FMRLabListening::Load(const TSharedPtr<FJsonObject>& Object)
{
	using namespace MRLabBodyLocal;
	LowShare = Num(Object, TEXT("low_share"), LowShare);
	LowSeconds = Num(Object, TEXT("low_seconds"), LowSeconds);
	MinSpeech = Num(Object, TEXT("min_speech"), MinSpeech);
	Delay = Num(Object, TEXT("delay"), Delay);
	MinGap = Num(Object, TEXT("min_gap"), MinGap);
	PerMinute = Num(Object, TEXT("per_minute"), PerMinute);
	MinVoiced = Num(Object, TEXT("min_voiced"), MinVoiced);
	Degrees = Num(Object, TEXT("degrees"), Degrees);
	Down = Num(Object, TEXT("down"), Down);
	Up = Num(Object, TEXT("up"), Up);
	DoubleChance = Num(Object, TEXT("double_chance"), DoubleChance);
	DoubleAfter = Num(Object, TEXT("double_after"), DoubleAfter);
	DoubleSize = Num(Object, TEXT("double_size"), DoubleSize);
	ConcernSlow = Num(Object, TEXT("concern_slow"), ConcernSlow);
	ConcernSize = Num(Object, TEXT("concern_size"), ConcernSize);
}

void FMRLabListening::Start(double At, bool bConcerned)
{
	const float Slow = bConcerned ? ConcernSlow : 1.f;
	const float Size = Degrees * (bConcerned ? ConcernSize : 1.f);
	Active.Add({ At, Size, Down * Slow, Up * Slow });
	if (FMath::FRand() < DoubleChance)
	{
		Active.Add({ At + DoubleAfter * Slow, Size * DoubleSize, Down * Slow, Up * Slow });
	}
	Starts.Add(At);
	++Count;
}

void FMRLabListening::Update(double Now, const TArray<FVector2f>& Frames, bool bVisitorVoice, bool bCue, bool bNod, float TurnAge, bool bConcerned)
{
	constexpr int32 Ring = 3000; // 30 s of voiced frames
	constexpr float Frame = 0.01f;
	if (Now - LowAt >= 1.0 && Voiced.Num() * Frame >= MinVoiced)
	{
		LowAt = Now;
		TArray<float> Sorted = Voiced;
		Sorted.Sort();
		LowHz = Sorted[FMath::Clamp(int32(LowShare * Sorted.Num()), 0, Sorted.Num() - 1)];
	}
	for (const FVector2f& F : Frames)
	{
		const bool bVoicedFrame = F.X > 0.f;
		if (bVoicedFrame)
		{
			LastHz = F.X;
			if (bVisitorVoice)
			{
				if (Voiced.Num() < Ring)
				{
					Voiced.Add(F.X);
				}
				else
				{
					Voiced[VoicedNext] = F.X;
					VoicedNext = (VoicedNext + 1) % Ring;
				}
			}
		}
		// Low-pitch stretch: voiced frames below LowHz in a row; one other frame is bridged.
		if (LowHz > 0.f && bVoicedFrame && F.X < LowHz)
		{
			++LowRun;
			Bridge = 0;
		}
		else if (LowRun > 0 && Bridge < 1)
		{
			++Bridge;
		}
		else
		{
			LowRun = 0;
			Bridge = 0;
			bStretchUsed = false;
		}
		if (!bStretchUsed && LowRun * Frame >= LowSeconds - 1e-4f && bCue && TurnAge >= MinSpeech)
		{
			bStretchUsed = true;
			++Cues;
			Starts.RemoveAll([Now](double T) { return Now - T > 60.0; });
			const double Last = Starts.Num() > 0 ? Starts.Last() : -1e9;
			if (PendingAt < 0.0 && Now + Delay - Last >= MinGap && Starts.Num() < PerMinute)
			{
				PendingAt = Now + Delay;
				bPendingForced = false;
			}
		}
	}
	if (PendingAt >= 0.0 && Now >= PendingAt)
	{
		if (bNod || bPendingForced)
		{
			Start(Now, bConcerned);
		}
		PendingAt = -1.0;
		bPendingForced = false;
	}
	// Shape: eased down, eased back up; overlapping nods add.
	Pitch = 0.f;
	Active.RemoveAll([Now](const FNod& N) { return Now - N.Start > N.DownS + N.UpS; });
	for (const FNod& N : Active)
	{
		const float T = float(Now - N.Start);
		if (T >= 0.f)
		{
			const float X = T < N.DownS ? T / N.DownS : 1.f - (T - N.DownS) / N.UpS;
			Pitch += N.Size * FMath::SmoothStep(0.f, 1.f, X);
		}
	}
}
