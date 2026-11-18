#include "MRLabGaze.h"

namespace
{
	float Num(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field, float Default)
	{
		double Value = Default;
		return Object.IsValid() && Object->TryGetNumberField(Field, Value) ? float(Value) : Default;
	}

	FVector2D Range(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field, FVector2D Default)
	{
		const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
		if (Object.IsValid() && Object->TryGetArrayField(Field, List) && List->Num() == 2)
		{
			return FVector2D((*List)[0]->AsNumber(), (*List)[1]->AsNumber());
		}
		return Default;
	}

	float Rand(FVector2D Range)
	{
		return float(FMath::FRandRange(Range.X, Range.Y));
	}

	// Exponential waiting time with this mean, never below Min (shifted, so the mean stays Mean).
	float Waiting(float Mean, float Min)
	{
		return Min + FMath::Max(0.f, Mean - Min) * -FMath::Loge(FMath::Max(FMath::FRand(), 1e-4f));
	}

	// One step of two critically damped stages in series towards Goal (95 % after Seconds): eased in and out.
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

	float Smooth(float X)
	{
		X = FMath::Clamp(X, 0.f, 1.f);
		return X * X * X * (10.f - 15.f * X + 6.f * X * X); // minimum jerk
	}

	constexpr double Forever = 1e12;
}

const TCHAR* MRLabTurnName(EMRLabTurn Turn)
{
	switch (Turn)
	{
	case EMRLabTurn::Outside: return TEXT("outside");
	case EMRLabTurn::Listening: return TEXT("listening");
	case EMRLabTurn::VisitorYielding: return TEXT("visitor_yielding");
	case EMRLabTurn::Speaking: return TEXT("speaking");
	case EMRLabTurn::FrankYielding: return TEXT("frank_yielding");
	case EMRLabTurn::Pause: return TEXT("pause");
	}
	return TEXT("?");
}

// --- Who speaks ---

void FMRLabTurns::Load(const TSharedPtr<FJsonObject>& Object)
{
	FrankVoiceWeight = Num(Object, TEXT("frank_voice_weight"), FrankVoiceWeight);
	VisitorThreshold = Num(Object, TEXT("visitor_threshold"), VisitorThreshold);
	EchoGuardSeconds = Num(Object, TEXT("echo_guard_seconds"), EchoGuardSeconds);
	MinVisitorSpeech = Num(Object, TEXT("min_visitor_speech"), MinVisitorSpeech);
	VisitorEndSeconds = Num(Object, TEXT("visitor_end_seconds"), VisitorEndSeconds);
	VisitorEndQuick = Num(Object, TEXT("visitor_end_quick"), VisitorEndQuick);
	FrankEndSeconds = Num(Object, TEXT("frank_end_seconds"), FrankEndSeconds);
	FrankEndQuick = Num(Object, TEXT("frank_end_quick"), FrankEndQuick);
	PhrasePauseSeconds = Num(Object, TEXT("phrase_pause_seconds"), PhrasePauseSeconds);
	YieldMaxSeconds = Num(Object, TEXT("yield_max_seconds"), YieldMaxSeconds);
	ConversationSeconds = Num(Object, TEXT("conversation_seconds"), ConversationSeconds);
}

void FMRLabTurns::Enter(EMRLabTurn Next, double Now)
{
	State = Next;
	StateSince = Now;
}

void FMRLabTurns::Update(double Now, float Speaking, float VisitorLevel, double TurnDoneAt, double TurnFinalAt)
{
	const bool bVoice = Speaking > FrankVoiceWeight;
	if (bVoice)
	{
		if (!bFrankVoice)
		{
			if (Now - FrankLastVoice >= PhrasePauseSeconds)
			{
				PhraseStartAt = Now;
			}
			FrankVoiceOn = Now;
		}
		FrankLastVoice = Now;
	}
	bFrankVoice = bVoice;

	// The microphone also hears Frank: it counts only after he has been silent a while (Q24).
	const bool bHeard = VisitorLevel > VisitorThreshold && Now - FrankLastVoice >= EchoGuardSeconds;
	if (bHeard)
	{
		if (!bVisitorVoice)
		{
			VisitorVoiceOn = Now;
		}
		VisitorLastVoice = Now;
	}
	bVisitorVoice = bHeard;

	if (bFrankVoice)
	{
		if (State != EMRLabTurn::Speaking)
		{
			FrankTurnStart = FrankVoiceOn;
			Enter(EMRLabTurn::Speaking, Now);
		}
		return;
	}
	if (bVisitorVoice && Now - VisitorVoiceOn >= MinVisitorSpeech && State != EMRLabTurn::Listening)
	{
		VisitorTurnStart = VisitorVoiceOn;
		Enter(EMRLabTurn::Listening, Now);
		return;
	}

	switch (State)
	{
	case EMRLabTurn::Listening:
	{
		const double Silence = Now - VisitorLastVoice;
		if (Silence >= VisitorEndSeconds || (Silence >= VisitorEndQuick && TurnDoneAt > VisitorTurnStart))
		{
			VisitorTurnEnd = VisitorLastVoice;
			Enter(EMRLabTurn::VisitorYielding, Now);
		}
		break;
	}
	case EMRLabTurn::Speaking:
	{
		const double Silence = Now - FrankLastVoice;
		if (Silence >= FrankEndSeconds || (Silence >= FrankEndQuick && TurnFinalAt > FrankTurnStart))
		{
			Enter(EMRLabTurn::FrankYielding, Now);
		}
		break;
	}
	case EMRLabTurn::VisitorYielding:
	case EMRLabTurn::FrankYielding:
		if (Now - StateSince > YieldMaxSeconds)
		{
			Enter(EMRLabTurn::Pause, Now);
		}
		break;
	default:
		break;
	}
	if (State != EMRLabTurn::Outside && State != EMRLabTurn::Listening && State != EMRLabTurn::Speaking
		&& Now - FMath::Max(FrankLastVoice, VisitorLastVoice) > ConversationSeconds)
	{
		Enter(EMRLabTurn::Outside, Now);
	}
}

// --- Eye curves ---

void FMRLabEyeTable::Solve(float Yaw, float Pitch, float OutValues[4]) const
{
	auto Invert = [this](int32 Curve, float Angle) // curve value for |Angle| on this curve's table, 0..1
	{
		float PrevValue = 0.f, PrevDeg = 0.f;
		for (int32 Step = 0; Step < 4; ++Step)
		{
			const float Value = 0.25f * (Step + 1);
			const float Deg = FMath::Abs(Degrees[Curve][Step]);
			if (Angle <= Deg)
			{
				return Deg > PrevDeg ? PrevValue + (Value - PrevValue) * (Angle - PrevDeg) / (Deg - PrevDeg) : Value;
			}
			PrevValue = Value;
			PrevDeg = Deg;
		}
		return 1.f;
	};
	for (int32 Curve = 0; Curve < 4; ++Curve)
	{
		OutValues[Curve] = 0.f;
	}
	// Horizontal: the curve (right or left) that turns the eye the way of Yaw; vertical likewise.
	for (int32 Curve : { 0, 1 })
	{
		if (Yaw != 0.f && FMath::Sign(Degrees[Curve][3]) == FMath::Sign(Yaw))
		{
			OutValues[Curve] = Invert(Curve, FMath::Abs(Yaw));
			break;
		}
	}
	for (int32 Curve : { 2, 3 })
	{
		if (Pitch != 0.f && FMath::Sign(Degrees[Curve][3]) == FMath::Sign(Pitch))
		{
			OutValues[Curve] = Invert(Curve, FMath::Abs(Pitch));
			break;
		}
	}
}

// --- Gaze ---

void FMRLabGaze::Load(const TSharedPtr<FJsonObject>& Object)
{
	if (!Object.IsValid())
	{
		return;
	}
	const TArray<TSharedPtr<FJsonValue>>* List = nullptr;
	WanderYaw = Range(Object, TEXT("wander_yaw"), WanderYaw);
	WanderPitch = Range(Object, TEXT("wander_pitch"), WanderPitch);
	WanderStep = Range(Object, TEXT("wander_step"), WanderStep);
	WanderEvery = Range(Object, TEXT("wander_every"), WanderEvery);
	WanderSeconds = Num(Object, TEXT("wander_seconds"), WanderSeconds);
	WanderCenterPull = Num(Object, TEXT("wander_center_pull"), WanderCenterPull);
	FarChance = Num(Object, TEXT("far_chance"), FarChance);
	WanderDistance = Num(Object, TEXT("wander_distance"), WanderDistance);
	HopSpread = Range(Object, TEXT("hop_spread"), HopSpread);
	WanderHeadYawShare = Num(Object, TEXT("wander_head_yaw_share"), WanderHeadYawShare);
	HeadDownShare = Num(Object, TEXT("head_down_share"), HeadDownShare);
	HeadUpShare = Num(Object, TEXT("head_up_share"), HeadUpShare);
	EyeShiftBase = Num(Object, TEXT("eye_shift_base"), EyeShiftBase);
	EyeShiftPerDegree = Num(Object, TEXT("eye_shift_per_degree"), EyeShiftPerDegree);
	EyeHopEvery = Range(Object, TEXT("eye_hop_every"), EyeHopEvery);
	JitterEvery = Range(Object, TEXT("jitter_every"), JitterEvery);
	JitterDegrees = Range(Object, TEXT("jitter_degrees"), JitterDegrees);
	if (Object->TryGetArrayField(TEXT("fallback_point"), List) && List->Num() == 3)
	{
		FallbackPoint = FVector((*List)[0]->AsNumber(), (*List)[1]->AsNumber(), (*List)[2]->AsNumber());
	}
	GlanceInterval = Range(Object, TEXT("glance_interval"), GlanceInterval);
	GlanceLength = Range(Object, TEXT("glance_length"), GlanceLength);
	NoticeDelay = Range(Object, TEXT("notice_delay"), NoticeDelay);
	CloseDistance = Num(Object, TEXT("close_distance"), CloseDistance);
	FastSpeed = Num(Object, TEXT("fast_speed"), FastSpeed);
	ListenAversionEvery = Num(Object, TEXT("listen_aversion_every"), ListenAversionEvery);
	ListenAversionLength = Num(Object, TEXT("listen_aversion_length"), ListenAversionLength);
	SpeakAversionEvery = Num(Object, TEXT("speak_aversion_every"), SpeakAversionEvery);
	SpeakAversionLength = Num(Object, TEXT("speak_aversion_length"), SpeakAversionLength);
	AversionDegrees = Range(Object, TEXT("aversion_degrees"), AversionDegrees);
	PhraseStartAvert = Num(Object, TEXT("phrase_start_avert"), PhraseStartAvert);
	PhraseAvertLength = Range(Object, TEXT("phrase_avert_length"), PhraseAvertLength);
	MinAversion = Num(Object, TEXT("min_aversion"), MinAversion);
	ContinueSeconds = Num(Object, TEXT("continue_seconds"), ContinueSeconds);
	ThinkDelay = Num(Object, TEXT("think_delay"), ThinkDelay);
	ThinkYaw = Range(Object, TEXT("think_yaw"), ThinkYaw);
	ThinkPitch = Range(Object, TEXT("think_pitch"), ThinkPitch);
	VisitorDelay = Range(Object, TEXT("visitor_delay"), VisitorDelay);
	VisitorShiftFactor = Num(Object, TEXT("visitor_shift_factor"), VisitorShiftFactor);
	ThinkAfterVoice = Range(Object, TEXT("think_after_voice"), ThinkAfterVoice);
	YieldHold = Range(Object, TEXT("yield_hold"), YieldHold);
	PauseGlanceEvery = Range(Object, TEXT("pause_glance_every"), PauseGlanceEvery);
	PauseGlanceLength = Range(Object, TEXT("pause_glance_length"), PauseGlanceLength);
	ScanEvery = Range(Object, TEXT("scan_every"), ScanEvery);
	HeadJoinDegrees = Num(Object, TEXT("head_join_degrees"), HeadJoinDegrees);
	HeadDelay = Num(Object, TEXT("head_delay"), HeadDelay);
	HeadSeconds = Num(Object, TEXT("head_seconds"), HeadSeconds);

	// Measured eye rotation per curve (README 4.10): {"L": {"neutral": [yaw, pitch], "right": [4 values], ...}, "R": ...}.
	const TCHAR* Sides[2] = { TEXT("L"), TEXT("R") };
	const TCHAR* Directions[4] = { TEXT("right"), TEXT("left"), TEXT("up"), TEXT("down") };
	const TCHAR* CurveNames[4] = { TEXT("Right"), TEXT("Left"), TEXT("Up"), TEXT("Down") };
	for (int32 Eye = 0; Eye < 2; ++Eye)
	{
		for (int32 Curve = 0; Curve < 4; ++Curve)
		{
			Eyes[Eye].Curves[Curve] = FName(FString::Printf(TEXT("CTRL_expressions_eyeLook%s%s"), CurveNames[Curve], Sides[Eye]));
		}
	}
	const TSharedPtr<FJsonObject>* EyesObject = nullptr;
	if (Object->TryGetObjectField(TEXT("eye_degrees"), EyesObject))
	{
		for (int32 Eye = 0; Eye < 2; ++Eye)
		{
			FMRLabEyeTable& Table = Eyes[Eye];
			const TSharedPtr<FJsonObject>* Side = nullptr;
			if (!(*EyesObject)->TryGetObjectField(Sides[Eye], Side))
			{
				continue;
			}
			const TArray<TSharedPtr<FJsonValue>>* Neutral = nullptr;
			if ((*Side)->TryGetArrayField(TEXT("neutral"), Neutral) && Neutral->Num() == 2)
			{
				Table.Neutral[0] = float((*Neutral)[0]->AsNumber());
				Table.Neutral[1] = float((*Neutral)[1]->AsNumber());
			}
			for (int32 Curve = 0; Curve < 4; ++Curve)
			{
				const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
				if ((*Side)->TryGetArrayField(Directions[Curve], Values) && Values->Num() == 4)
				{
					for (int32 Step = 0; Step < 4; ++Step)
					{
						Table.Degrees[Curve][Step] = float((*Values)[Step]->AsNumber());
					}
				}
			}
		}
	}
}

FVector FMRLabGaze::Local(const FMRLabGazeInput& In, const FVector& Point) const
{
	const FVector Left = FVector::CrossProduct(In.FrankForward, FVector::UpVector);
	return In.FrankFeet + In.FrankForward * Point.X + Left * Point.Y + FVector::UpVector * Point.Z;
}

FVector FMRLabGaze::VisitorPoint(const FMRLabGazeInput& In) const
{
	return In.bTracked ? In.Visitor : Local(In, FallbackPoint);
}

FVector FMRLabGaze::Offset(const FMRLabGazeInput& In, const FVector& Around, float Yaw, float Pitch) const
{
	const FVector Mid = (In.EyeL + In.EyeR) * 0.5;
	const FVector Delta = Around - Mid;
	const FRotator Direction = Delta.Rotation();
	return Mid + FRotator(Direction.Pitch + Pitch, Direction.Yaw + Yaw, 0.f).Vector() * Delta.Size();
}

void FMRLabGaze::StartSaccade(const FMRLabGazeInput& In, const FVector& To)
{
	// From where the eyes look now, eased in and out (minimum jerk), slower than a reflex saccade.
	const FVector Mid = (In.EyeL + In.EyeR) * 0.5;
	const FVector From = GazePoint - Mid;
	const FVector Dest = To - Mid;
	FromDir = From.GetSafeNormal();
	ToDir = Dest.GetSafeNormal();
	FromDist = From.Size();
	ToDist = Dest.Size();
	const float Degrees = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FVector::DotProduct(FromDir, ToDir), -1.f, 1.f)));
	SaccadeStart = In.Now;
	SaccadeSeconds = EyeShiftBase + EyeShiftPerDegree * Degrees;
	SaccadeEnd = To;
	Fixation = To;
}

void FMRLabGaze::LookAt(const FMRLabGazeInput& In, EKind NewKind, const FVector& Point, bool bFollowVisitor, double NewUntil)
{
	const FVector Mid = (In.EyeL + In.EyeR) * 0.5;
	Kind = NewKind;
	Until = NewUntil;
	bTrackVisitor = bFollowVisitor;
	bWander = false;
	Scan = FVector::ZeroVector;
	NextScan = In.Now + Rand(ScanEvery);
	NextJitter = In.Now + Rand(JitterEvery);
	Target = Point;

	const FVector From = (GazePoint - Mid).GetSafeNormal();
	const FVector To = (Target - Mid).GetSafeNormal();
	const float Degrees = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FVector::DotProduct(From, To), -1.f, 1.f)));
	LastShiftDegrees = Degrees;
	LastShiftAt = In.Now;

	StartSaccade(In, Target);
	if (bFollowVisitor && Degrees > 10.f)
	{
		SaccadeSeconds *= VisitorShiftFactor; // no rush to look at the visitor
	}

	// The head turns to the visitor whenever he looks at them, and joins other shifts above HeadJoinDegrees (seen from
	// the head), a little after the eyes; small aversions are eyes only.
	const FVector HeadPos = In.Head.GetLocation();
	const float HeadAngle = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(
		FVector::DotProduct((Target - HeadPos).GetSafeNormal(), (HeadAnchor - HeadPos).GetSafeNormal()), -1.f, 1.f)));
	if (bFollowVisitor || HeadAngle > HeadJoinDegrees)
	{
		PendingAnchor = Target;
		bPendingFollowsVisitor = bFollowVisitor;
		HeadMoveAt = In.Now + HeadDelay;
	}
}

void FMRLabGaze::ChooseOwn(const FMRLabGazeInput& In)
{
	Kind = EKind::Own;
	Until = Forever;
	if (bWander)
	{
		return; // already looking around: the drift goes on by itself
	}
	// Start looking around from where he looks now; the eyes go first, the head follows.
	const FVector Mid = (In.EyeL + In.EyeR) * 0.5;
	const FRotator From = (GazePoint - Mid).Rotation();
	AttnYaw = AttnYawA = GoalYaw = FMath::Clamp(FMath::FindDeltaAngleDegrees(In.FrankForward.Rotation().Yaw, From.Yaw), WanderYaw.X, WanderYaw.Y);
	AttnPitch = AttnPitchA = GoalPitch = FMath::Clamp(From.Pitch, WanderPitch.X, WanderPitch.Y);
	AttnYawVel = AttnPitchVel = AttnYawVelA = AttnPitchVelA = 0.f;
	NextGoalAt = In.Now;
	NextHop = In.Now;
	bTrackVisitor = false;
	bWander = true;
	HeadMoveAt = -1.0;
	bHeadFollowsVisitor = false;
}

void FMRLabGaze::Update(const FMRLabGazeInput& In)
{
	const FMRLabTurns& T = *In.Turns;
	const double Now = In.Now;
	const FVector Mid = (In.EyeL + In.EyeR) * 0.5;

	if (In.bTracked)
	{
		if (bWasTracked && In.DeltaTime > 0.f)
		{
			const float Speed = (In.Visitor - LastVisitor).Size() / In.DeltaTime;
			VisitorSpeed += (Speed - VisitorSpeed) * FMath::Min(1.f, In.DeltaTime / 0.25f);
		}
		LastVisitor = In.Visitor;
	}
	const bool bArrived = In.bTracked && !bWasTracked;
	bWasTracked = In.bTracked;
	const FVector Visitor = VisitorPoint(In);

	if (!bStarted)
	{
		bStarted = true;
		GazePoint = Local(In, FallbackPoint);
		Fixation = GazePoint;
		HeadAnchor = GazePoint;
		HeadTarget = GazePoint;
		ChooseOwn(In);
		NextGlance = Now + Rand(GlanceInterval);
	}
	const bool bTurnChanged = T.State != LastTurn;
	if (bTurnChanged && LastTurn == EMRLabTurn::Speaking)
	{
		SpeakingEndedAt = Now;
	}
	if (bTurnChanged && T.State != EMRLabTurn::Listening)
	{
		ReturnAt = -1.0;
	}
	LastTurn = T.State;

	auto OnVisitor = [&](EKind NewKind, double NewUntil) { LookAt(In, NewKind, Visitor, true, NewUntil); };
	auto Avert = [&](float Length)
	{
		const bool bDown = FMath::FRand() < 0.3f;
		const float Yaw = bDown ? FMath::FRandRange(-4.f, 4.f) : Rand(AversionDegrees) * (FMath::RandBool() ? 1.f : -1.f);
		const float Pitch = bDown ? -Rand(AversionDegrees) : FMath::FRandRange(-3.f, 3.f);
		LookAt(In, EKind::Aversion, Offset(In, Visitor, Yaw, Pitch), false, Now + Length);
		AvertStart = Now;
	};

	switch (T.State)
	{
	case EMRLabTurn::Outside:
		if (bTurnChanged)
		{
			ChooseOwn(In);
			NextGlance = Now + Rand(GlanceInterval);
		}
		if (bArrived)
		{
			NoticeAt = Now + Rand(NoticeDelay);
		}
		{
			// Someone is assumed in front even without tracking (owner, 2026-11-18): then at the fallback point.
			const bool bAlert = (Visitor - Mid).Size() < CloseDistance || VisitorSpeed > FastSpeed;
			if ((NoticeAt > 0.0 && Now >= NoticeAt) || (Kind != EKind::Glance && Now >= NextGlance))
			{
				NoticeAt = -1.0;
				OnVisitor(EKind::Glance, Now + Rand(GlanceLength));
				NextGlance = Until + Rand(GlanceInterval) * (bAlert ? 0.5f : 1.f);
				break;
			}
		}
		if (Now >= Until)
		{
			ChooseOwn(In);
		}
		break;

	case EMRLabTurn::Listening:
		if (bTurnChanged)
		{
			if (Kind != EKind::Visitor)
			{
				ReturnAt = Now + Rand(VisitorDelay); // he hears them, then turns to them without rushing
			}
			NextAversion = Now + Waiting(ListenAversionEvery * (1.f + In.Rapport), 1.f);
		}
		if (ReturnAt > 0.0)
		{
			if (Now >= ReturnAt)
			{
				ReturnAt = -1.0;
				OnVisitor(EKind::Visitor, Forever);
			}
			break;
		}
		if (Kind == EKind::Aversion)
		{
			if (Now >= Until)
			{
				OnVisitor(EKind::Visitor, Forever);
			}
		}
		else if (Now >= NextAversion)
		{
			// Vetoes: not in the first second of their turn, not in a silence that may end it; a vetoed aversion
			// is tried again shortly.
			if (Now - T.VisitorTurnStart >= 1.0 && Now - T.VisitorLastVoice < 0.25)
			{
				Avert(FMath::Clamp(ListenAversionLength + 0.3f * FMath::FRandRange(-1.f, 1.f), 0.6f, 2.f));
				NextAversion = Now + Waiting(ListenAversionEvery * (1.f + In.Rapport), 1.f);
			}
			else
			{
				NextAversion = Now + 0.3;
			}
		}
		break;

	case EMRLabTurn::VisitorYielding:
		if (bTurnChanged && Kind != EKind::Visitor && Kind != EKind::Thinking)
		{
			OnVisitor(EKind::Visitor, Forever);
		}
		if (Kind != EKind::Thinking && Now - T.VisitorTurnEnd >= ThinkDelay)
		{
			// Thinking: up and aside, mostly with the eyes.
			const float Yaw = Rand(ThinkYaw) * (FMath::RandBool() ? 1.f : -1.f);
			LookAt(In, EKind::Thinking, Offset(In, Visitor, Yaw, Rand(ThinkPitch)), false, Forever);
			ThinkUntil = -1.0;
		}
		break;

	case EMRLabTurn::Speaking:
		if (bTurnChanged)
		{
			// Back within ContinueSeconds (a sentence end inside an answer): the same turn, its timing goes on and
			// the restart counts as a phrase start.
			const bool bContinued = Now - SpeakingEndedAt < ContinueSeconds;
			if (Kind == EKind::Thinking)
			{
				ThinkUntil = Now + Rand(ThinkAfterVoice);
			}
			else if (Kind != EKind::Visitor && !(bContinued && Kind == EKind::Aversion))
			{
				OnVisitor(EKind::Visitor, Forever);
			}
			if (!bContinued)
			{
				NextAversion = Now + Waiting(SpeakAversionEvery, 1.f);
				LastPhraseSeen = T.PhraseStartAt;
			}
		}
		if (Kind == EKind::Thinking)
		{
			if (ThinkUntil > 0.0 && Now >= ThinkUntil)
			{
				ThinkUntil = -1.0;
				OnVisitor(EKind::Visitor, Forever);
			}
			break;
		}
		if (T.PhraseStartAt > LastPhraseSeen)
		{
			LastPhraseSeen = T.PhraseStartAt;
			if (Kind == EKind::Visitor && FMath::FRand() < PhraseStartAvert)
			{
				Avert(Rand(PhraseAvertLength));
				NextAversion = Until + Waiting(SpeakAversionEvery, 1.f);
				break;
			}
		}
		if (Kind == EKind::Aversion)
		{
			// Back on the visitor at a phrase end (a pause as long as a phrase break), or when the aversion is over.
			if (Now >= Until || (Now - AvertStart >= MinAversion && !T.bFrankVoice && Now - T.FrankLastVoice >= T.PhrasePauseSeconds))
			{
				OnVisitor(EKind::Visitor, Forever);
			}
		}
		else if (Kind != EKind::Visitor)
		{
			OnVisitor(EKind::Visitor, Forever);
		}
		else if (Now >= NextAversion)
		{
			if (T.bFrankVoice)
			{
				Avert(FMath::Clamp(SpeakAversionLength + 0.5f * FMath::FRandRange(-1.f, 1.f), 1.f, 3.f));
				NextAversion = Now + Waiting(SpeakAversionEvery, 1.f);
			}
			else
			{
				NextAversion = Now + 0.3; // in a pause of his voice: try again when he speaks
			}
		}
		break;

	case EMRLabTurn::FrankYielding:
		if (bTurnChanged)
		{
			OnVisitor(EKind::Visitor, Now + Rand(YieldHold));
		}
		if (Now >= Until)
		{
			ChooseOwn(In); // the glance away after waiting for an answer; the pause takes over
		}
		break;

	case EMRLabTurn::Pause:
		if (bTurnChanged)
		{
			if (Kind != EKind::Own)
			{
				ChooseOwn(In);
			}
			NextGlance = Now + Rand(PauseGlanceEvery);
		}
		if (Kind == EKind::Glance)
		{
			if (Now >= Until)
			{
				ChooseOwn(In);
				NextGlance = Now + Rand(PauseGlanceEvery);
			}
		}
		else if (Now >= NextGlance)
		{
			OnVisitor(EKind::Glance, Now + Rand(PauseGlanceLength));
		}
		else if (Now >= Until)
		{
			ChooseOwn(In);
		}
		break;
	}

	// On the visitor: follow them, with small scanning saccades over the face (mostly the eye region).
	if (bTrackVisitor)
	{
		if (Now >= NextScan)
		{
			NextScan = Now + Rand(ScanEvery);
			const float Pick = FMath::FRand();
			const FVector Side = FVector::CrossProduct(FVector::UpVector, (Visitor - Mid).GetSafeNormal2D());
			const FVector NewScan = Pick < 0.5f ? FVector::ZeroVector
				: Pick < 0.8f ? Side * (FMath::RandBool() ? 3.f : -3.f)
				: FVector(0.f, 0.f, -7.f);
			if (!NewScan.Equals(Scan))
			{
				const double KeepUntil = Until;
				const EKind KeepKind = Kind;
				LookAt(In, Kind, Visitor + NewScan, true, KeepUntil);
				Kind = KeepKind;
				Scan = NewScan;
				NextScan = Now + Rand(ScanEvery);
			}
		}
		// A jump of the visitor point (tracking found or lost) is an eye movement, not a teleport.
		const FVector Next = Visitor + Scan;
		const float Jump = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(
			FVector::DotProduct((Next - Mid).GetSafeNormal(), (Target - Mid).GetSafeNormal()), -1.f, 1.f)));
		if (Jump > 5.f)
		{
			const double KeepUntil = Until;
			const EKind KeepKind = Kind;
			const FVector KeepScan = Scan;
			LookAt(In, Kind, Next, true, KeepUntil);
			Kind = KeepKind;
			Scan = KeepScan;
		}
		Target = Next;
		Fixation = Target;
	}
	else if (bWander)
	{
		// Looking around: the attention drifts on a smooth random path towards goals that change before they are reached
		// (no resting points); the eyes jump around it in short fixations, a little ahead; the head follows part of it.
		if (Now >= NextGoalAt)
		{
			NextGoalAt = Now + Rand(WanderEvery);
			if (FMath::FRand() < FarChance)
			{
				GoalYaw = Rand(WanderYaw);
				GoalPitch = Rand(WanderPitch);
			}
			else
			{
				const float Step = Rand(WanderStep);
				const float Angle = FMath::FRandRange(0.f, 2.f * PI);
				GoalYaw = GoalYaw * (1.f - WanderCenterPull) + Step * FMath::Cos(Angle);
				GoalPitch = GoalPitch * (1.f - WanderCenterPull) + Step * 0.6f * FMath::Sin(Angle);
			}
			GoalYaw = FMath::Clamp(GoalYaw, WanderYaw.X, WanderYaw.Y);
			GoalPitch = FMath::Clamp(GoalPitch, WanderPitch.X, WanderPitch.Y);
		}
		Spring2(AttnYawA, AttnYawVelA, AttnYaw, AttnYawVel, GoalYaw, WanderSeconds, In.DeltaTime);
		Spring2(AttnPitchA, AttnPitchVelA, AttnPitch, AttnPitchVel, GoalPitch, WanderSeconds, In.DeltaTime);
		const float ForwardYaw = In.FrankForward.Rotation().Yaw;
		Attention = Mid + FRotator(AttnPitch, ForwardYaw + AttnYaw, 0.f).Vector() * WanderDistance;
		HeadAnchor = Attention;
		if (Now >= NextHop && Now - SaccadeStart > SaccadeSeconds)
		{
			NextHop = Now + Rand(EyeHopEvery);
			const float Lead = FMath::FRandRange(0.2f, 0.5f);
			const float Spread = Rand(HopSpread);
			const float Angle = FMath::FRandRange(0.f, 2.f * PI);
			const FRotator Look(AttnPitch + AttnPitchVel * Lead + 0.6f * Spread * FMath::Sin(Angle),
				ForwardYaw + AttnYaw + AttnYawVel * Lead + Spread * FMath::Cos(Angle), 0.f);
			StartSaccade(In, Mid + Look.Vector() * WanderDistance);
		}
	}
	else if (Now >= NextJitter && Now - SaccadeStart > SaccadeSeconds)
	{
		// Holding a point: small movements around it, not a fixed stare.
		NextJitter = Now + Rand(JitterEvery);
		const float Size = Rand(JitterDegrees);
		const float Angle = FMath::FRandRange(0.f, 2.f * PI);
		StartSaccade(In, Offset(In, Target, Size * FMath::Cos(Angle), Size * FMath::Sin(Angle)));
	}

	// Where the eyes point now: along the eased movement, then on the fixation point.
	const float S = SaccadeSeconds > 0.f ? float((Now - SaccadeStart) / SaccadeSeconds) : 1.f;
	if (S < 1.f)
	{
		const float M = Smooth(S);
		const FQuat Turn = FQuat::Slerp(FQuat::Identity, FQuat::FindBetweenNormals(FromDir, ToDir), M);
		GazePoint = Mid + Turn.RotateVector(FromDir) * FMath::Lerp(FromDist, ToDist, M);
	}
	else
	{
		GazePoint = Fixation;
	}

	// Each eye from its own position (vergence), in the head bone's frame (X up, Y forward, Z to his right).
	const FVector EyePositions[2] = { In.EyeL, In.EyeR };
	for (int32 Eye = 0; Eye < 2; ++Eye)
	{
		const FVector Dir = In.Head.InverseTransformVectorNoScale((GazePoint - EyePositions[Eye]).GetSafeNormal());
		const float Yaw = FMath::RadiansToDegrees(FMath::Atan2(Dir.Z, Dir.Y));
		const float Pitch = FMath::RadiansToDegrees(FMath::Atan2(Dir.X, FMath::Sqrt(Dir.Y * Dir.Y + Dir.Z * Dir.Z)));
		YawPitch[Eye][0] = Yaw;
		YawPitch[Eye][1] = Pitch;
		Eyes[Eye].Solve(Yaw - Eyes[Eye].Neutral[0], Pitch - Eyes[Eye].Neutral[1], Curves[Eye]);
	}

	// Head target: the anchor, eased; it follows the visitor while anchored on them.
	if (HeadMoveAt > 0.0 && Now >= HeadMoveAt)
	{
		HeadMoveAt = -1.0;
		HeadAnchor = PendingAnchor;
		bHeadFollowsVisitor = bPendingFollowsVisitor;
	}
	if (bHeadFollowsVisitor)
	{
		HeadAnchor = Visitor;
	}
	// Two critically damped stages in series on the head target's direction seen from the eyes: a bell-shaped speed
	// (peak about 0.4 x HeadSeconds after the start), no overshoot, smooth also when the visitor moves.
	// The head takes only part of a look down or up and, while he looks around, of the sideways drift; the eyes do the rest.
	const FVector ToAnchor = HeadAnchor - Mid;
	const FRotator Toward = ToAnchor.Rotation();
	const float FrankYaw = In.FrankForward.Rotation().Yaw;
	FRotator Goal;
	Goal.Yaw = FrankYaw + FMath::FindDeltaAngleDegrees(FrankYaw, Toward.Yaw) * (bWander ? WanderHeadYawShare : 1.f);
	Goal.Pitch = Toward.Pitch * (Toward.Pitch < 0.f ? HeadDownShare : HeadUpShare);
	if (!bHeadInit)
	{
		bHeadInit = true;
		HeadYaw = HeadYawA = Goal.Yaw;
		HeadPitch = HeadPitchA = Goal.Pitch;
		HeadDist = ToAnchor.Size();
	}
	const float W = 7.75f / FMath::Max(HeadSeconds, 0.05f); // 95 % of a step after HeadSeconds
	const float Dt = FMath::Min(In.DeltaTime, 0.25f);
	auto Spring = [W, Dt](float& X, float& V, float GoalValue)
	{
		const float D = X - GoalValue;
		const float C = V + W * D;
		const float E = FMath::Exp(-W * Dt);
		X = GoalValue + (D + C * Dt) * E;
		V = (V - W * C * Dt) * E;
	};
	Spring(HeadYawA, HeadYawVelA, HeadYawA + FMath::FindDeltaAngleDegrees(HeadYawA, Goal.Yaw));
	Spring(HeadPitchA, HeadPitchVelA, Goal.Pitch);
	Spring(HeadYaw, HeadYawVel, HeadYaw + FMath::FindDeltaAngleDegrees(HeadYaw, HeadYawA));
	Spring(HeadPitch, HeadPitchVel, HeadPitchA);
	HeadDist += (ToAnchor.Size() - HeadDist) * (1.f - FMath::Exp(-Dt / 0.3f));
	HeadTarget = Mid + FRotator(HeadPitch, HeadYaw, 0.f).Vector() * HeadDist;
	bHeadValid = true;
}

// --- Blinks ---

void FMRLabBlinks::Load(const TSharedPtr<FJsonObject>& Object)
{
	RestPerMinute = Num(Object, TEXT("rest_per_minute"), RestPerMinute);
	SpeakingPerMinute = Num(Object, TEXT("speaking_per_minute"), SpeakingPerMinute);
	MinInterval = Num(Object, TEXT("min_interval"), MinInterval);
	CloseSeconds = Num(Object, TEXT("close_seconds"), CloseSeconds);
	OpenSeconds = Num(Object, TEXT("open_seconds"), OpenSeconds);
	LongClosed = Range(Object, TEXT("long_closed"), LongClosed);
	ShiftDegrees = Num(Object, TEXT("shift_degrees"), ShiftDegrees);
	ShiftProbability = Num(Object, TEXT("shift_probability"), ShiftProbability);
	UnderstoodProbability = Num(Object, TEXT("understood_probability"), UnderstoodProbability);
	UnderstoodMinTurn = Num(Object, TEXT("understood_min_turn"), UnderstoodMinTurn);
	ModelGuard = Num(Object, TEXT("model_guard"), ModelGuard);
	WaitForPause = Num(Object, TEXT("wait_for_pause"), WaitForPause);
	ArousalGain = Num(Object, TEXT("arousal_gain"), ArousalGain);
}

void FMRLabBlinks::Schedule(double Now, float PerMinute)
{
	NextAt = Now + Waiting(60.f / FMath::Max(PerMinute, 1.f), MinInterval);
	DueSince = -1.0;
}

void FMRLabBlinks::Start(double Now, float Closed)
{
	BlinkStart = Now;
	BlinkClosed = Closed;
	LastBlink = Now;
	++OwnCount;
}

void FMRLabBlinks::Update(double Now, const FMRLabTurns& Turns, const FMRLabGaze& Gaze, float ModelBlink, float Arousal)
{
	const float PerMinute = (Turns.State == EMRLabTurn::Speaking ? SpeakingPerMinute : RestPerMinute)
		* FMath::Max(0.2f, 1.f + ArousalGain * Arousal);
	if (NextAt < 0.0)
	{
		Schedule(Now, PerMinute);
	}

	// The lip sync model's own blinks count as blinks.
	if (ModelBlink > 0.5f && !bModelBlinking)
	{
		bModelBlinking = true;
		++ModelCount;
		LastBlink = Now;
		Schedule(Now, PerMinute);
	}
	else if (ModelBlink < 0.3f)
	{
		bModelBlinking = false;
	}

	const bool bBusy = Now - BlinkStart < CloseSeconds + BlinkClosed + OpenSeconds || bModelBlinking;
	const bool bClear = !bBusy && Now - LastBlink >= ModelGuard;

	if (Gaze.LastShiftAt > HandledShift)
	{
		HandledShift = Gaze.LastShiftAt;
		if (Gaze.LastShiftDegrees > ShiftDegrees && bClear && FMath::FRand() < ShiftProbability)
		{
			Start(Now, 0.f);
			Schedule(Now, PerMinute);
		}
	}
	if (Turns.State != LastTurn)
	{
		LastTurn = Turns.State;
		if (Turns.State == EMRLabTurn::VisitorYielding && Turns.VisitorTurnEnd - Turns.VisitorTurnStart >= UnderstoodMinTurn
			&& bClear && FMath::FRand() < UnderstoodProbability)
		{
			Start(Now, Rand(LongClosed));
			Schedule(Now, PerMinute);
		}
	}
	if (Now >= NextAt && !bBusy)
	{
		if (DueSince < 0.0)
		{
			DueSince = Now;
		}
		// While he speaks, a blink waits a little for a pause in his voice.
		if (!Turns.bFrankVoice || Now - DueSince >= WaitForPause)
		{
			if (Now - LastBlink >= ModelGuard)
			{
				Start(Now, 0.f);
			}
			Schedule(Now, PerMinute);
		}
	}

	const double T = Now - BlinkStart;
	if (T < CloseSeconds)
	{
		Value = FMath::SmoothStep(0.f, 1.f, float(T / CloseSeconds));
	}
	else if (T < CloseSeconds + BlinkClosed)
	{
		Value = 1.f;
	}
	else if (T < CloseSeconds + BlinkClosed + OpenSeconds)
	{
		Value = 1.f - FMath::SmoothStep(0.f, 1.f, float((T - CloseSeconds - BlinkClosed) / OpenSeconds));
	}
	else
	{
		Value = 0.f;
	}
}
