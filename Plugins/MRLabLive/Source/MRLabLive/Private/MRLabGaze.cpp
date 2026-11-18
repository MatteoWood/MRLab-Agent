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
	if (Object->TryGetArrayField(TEXT("own_regions"), List))
	{
		// [{"min": [f, l, u], "max": [f, l, u], "weight": w}, ...]
		OwnRegions.Reset();
		for (const TSharedPtr<FJsonValue>& Value : *List)
		{
			const TSharedPtr<FJsonObject> Entry = Value->AsObject();
			const TArray<TSharedPtr<FJsonValue>>* Lo = nullptr;
			const TArray<TSharedPtr<FJsonValue>>* Hi = nullptr;
			if (Entry.IsValid() && Entry->TryGetArrayField(TEXT("min"), Lo) && Entry->TryGetArrayField(TEXT("max"), Hi) && Lo->Num() == 3 && Hi->Num() == 3)
			{
				FRegion& Region = OwnRegions.AddDefaulted_GetRef();
				Region.Min = FVector((*Lo)[0]->AsNumber(), (*Lo)[1]->AsNumber(), (*Lo)[2]->AsNumber());
				Region.Max = FVector((*Hi)[0]->AsNumber(), (*Hi)[1]->AsNumber(), (*Hi)[2]->AsNumber());
				Region.Weight = Num(Entry, TEXT("weight"), 1.f);
			}
		}
	}
	NearDegrees = Num(Object, TEXT("near_degrees"), NearDegrees);
	FarChance = Num(Object, TEXT("far_chance"), FarChance);
	EyeShiftBase = Num(Object, TEXT("eye_shift_base"), EyeShiftBase);
	EyeShiftPerDegree = Num(Object, TEXT("eye_shift_per_degree"), EyeShiftPerDegree);
	WanderSpeed = Range(Object, TEXT("wander_speed"), WanderSpeed);
	WanderDwell = Range(Object, TEXT("wander_dwell"), WanderDwell);
	EyeHopEvery = Range(Object, TEXT("eye_hop_every"), EyeHopEvery);
	EyeLead = Range(Object, TEXT("eye_lead"), EyeLead);
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

FVector FMRLabGaze::RandomOwnPoint(const FMRLabGazeInput& In) const
{
	float Total = 0.f;
	for (const FRegion& Region : OwnRegions)
	{
		Total += Region.Weight;
	}
	float Pick = FMath::FRand() * Total;
	for (const FRegion& Region : OwnRegions)
	{
		Pick -= Region.Weight;
		if (Pick <= 0.f)
		{
			return Local(In, FVector(FMath::FRandRange(Region.Min.X, Region.Max.X), FMath::FRandRange(Region.Min.Y, Region.Max.Y),
				FMath::FRandRange(Region.Min.Z, Region.Max.Z)));
		}
	}
	return Local(In, FallbackPoint);
}

FVector FMRLabGaze::WanderPoint(const FVector& Mid, double Time) const
{
	const float S = Smooth(WanderSeconds > 0.f ? float((Time - WanderStart) / WanderSeconds) : 1.f);
	const FVector Dir = FQuat::Slerp(FQuat::Identity, FQuat::FindBetweenNormals(WanderFromDir, WanderToDir), S).RotateVector(WanderFromDir);
	return Mid + Dir * FMath::Lerp(WanderFromDist, WanderToDist, S);
}

void FMRLabGaze::ChooseOwn(const FMRLabGazeInput& In)
{
	const FVector Mid = (In.EyeL + In.EyeR) * 0.5;
	const FVector From = bWander ? Attention : GazePoint;
	// Mostly a point near where his attention is (not the same spot), sometimes anywhere in his room.
	const FVector Current = (From - Mid).GetSafeNormal();
	const bool bAnywhere = FMath::FRand() < FarChance;
	FVector Best = RandomOwnPoint(In);
	float BestScore = -1.f;
	for (int32 Try = 0; Try < 16; ++Try)
	{
		const FVector Candidate = RandomOwnPoint(In);
		const float Angle = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FVector::DotProduct(Current, (Candidate - Mid).GetSafeNormal()), -1.f, 1.f)));
		const float Score = (Angle < 4.f ? 0.05f : (bAnywhere ? 1.f : FMath::Exp(-Angle / FMath::Max(NearDegrees, 1.f)))) * FMath::FRand();
		if (Score > BestScore)
		{
			BestScore = Score;
			Best = Candidate;
		}
	}
	if (OwnRegions.Num() == 0)
	{
		Best = Local(In, FallbackPoint);
	}

	// Looking around: the attention glides there (eased), the head follows it, the eyes hop along.
	const bool bWasWandering = bWander;
	Kind = EKind::Own;
	bTrackVisitor = false;
	bWander = true;
	Target = Best;
	WanderFromDir = Current;
	WanderFromDist = (From - Mid).Size();
	WanderToDir = (Best - Mid).GetSafeNormal();
	WanderToDist = (Best - Mid).Size();
	const float Degrees = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FVector::DotProduct(WanderFromDir, WanderToDir), -1.f, 1.f)));
	WanderStart = In.Now;
	WanderSeconds = FMath::Max(0.4f, Degrees / FMath::Max(Rand(WanderSpeed), 1.f));
	Until = In.Now + WanderSeconds + Rand(WanderDwell);
	Attention = From;
	HeadMoveAt = -1.0;
	bHeadFollowsVisitor = false;
	if (!bWasWandering)
	{
		NextHop = In.Now; // from the visitor or an aversion: the eyes go first
		LastShiftDegrees = Degrees;
		LastShiftAt = In.Now;
	}
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
				OnVisitor(EKind::Visitor, Forever);
			}
			NextAversion = Now + Waiting(ListenAversionEvery * (1.f + In.Rapport), 1.f);
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
			// Thinking: up and aside; large enough that the head joins a little.
			const float Yaw = FMath::FRandRange(15.f, 25.f) * (FMath::RandBool() ? 1.f : -1.f);
			LookAt(In, EKind::Thinking, Offset(In, Visitor, Yaw, FMath::FRandRange(5.f, 15.f)), false, Forever);
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
		// Looking around: the head follows the gliding attention; the eyes hop to it, a little ahead, and hold.
		Attention = WanderPoint(Mid, Now);
		HeadAnchor = Attention;
		if (Now >= NextHop && Now - SaccadeStart > SaccadeSeconds)
		{
			NextHop = Now + Rand(EyeHopEvery);
			const FVector Ahead = WanderPoint(Mid, FMath::Min(Now + Rand(EyeLead), WanderStart + WanderSeconds));
			StartSaccade(In, Offset(In, Ahead, FMath::FRandRange(-1.5f, 1.5f), FMath::FRandRange(-1.5f, 1.5f)));
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
	const FVector ToAnchor = HeadAnchor - Mid;
	const FRotator Goal = ToAnchor.Rotation();
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
