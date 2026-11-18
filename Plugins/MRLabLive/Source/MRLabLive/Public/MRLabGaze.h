#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

// Frank's eyes and blinks (README 4.10, Step 9C), owned and fed by UMRLabBehaviorComponent. Plain structs, game thread.

/** Who speaks, as far as gaze and blinks need it (the reflex layer's conversation states; 9D/9E add the rest). */
enum class EMRLabTurn : uint8
{
	Outside,         // no conversation (nobody spoke for a while)
	Listening,       // the visitor speaks
	VisitorYielding, // the visitor's turn ended, Frank has not started
	Speaking,        // Frank's voice is heard
	FrankYielding,   // Frank's turn ended, the visitor has not started
	Pause,           // a conversation, both silent after the yielding phase
};

const TCHAR* MRLabTurnName(EMRLabTurn Turn);

struct FMRLabTurns
{
	// Settings ("turns" in Config/MRLabBehavior.json).
	float FrankVoiceWeight = 0.3f;    // SpeakingWeight above this: his voice is heard
	float VisitorThreshold = 0.02f;   // RMS of the visitor audio above this: someone speaks
	float EchoGuardSeconds = 0.4f;    // the microphone counts only after Frank has been silent this long (Q24)
	float MinVisitorSpeech = 0.15f;   // a visitor turn starts after this much voice
	float VisitorEndSeconds = 0.7f;   // silence that ends a visitor turn
	float VisitorEndQuick = 0.25f;    // ... or this silence after turn_done / asks_frank
	float FrankEndSeconds = 0.6f;     // silence that ends Frank's turn
	float FrankEndQuick = 0.2f;       // ... or this silence after turn_final
	float PhrasePauseSeconds = 0.25f; // his voice after at least this pause starts a phrase
	float YieldMaxSeconds = 5.f;      // a yielding phase becomes a pause after this
	float ConversationSeconds = 15.f; // a conversation ends after this much silence

	void Load(const TSharedPtr<FJsonObject>& Object);
	/** Advance by one tick. TurnDoneAt / TurnFinalAt: times of the latest Decisions saying the visitor's / Frank's
	 * turn is done (0 if none). */
	void Update(double Now, float Speaking, float VisitorLevel, double TurnDoneAt, double TurnFinalAt);

	EMRLabTurn State = EMRLabTurn::Outside;
	double StateSince = 0.0;
	bool bFrankVoice = false;
	bool bVisitorVoice = false;
	double FrankVoiceOn = -1e9;    // start of his current or last stretch of voice
	double FrankLastVoice = -1e9;  // last tick with his voice
	double FrankTurnStart = -1e9;
	double PhraseStartAt = -1e9;   // start of his latest phrase (voice after a pause)
	double VisitorVoiceOn = -1e9;
	double VisitorLastVoice = -1e9;
	double VisitorTurnStart = -1e9;
	double VisitorTurnEnd = -1e9;

private:
	void Enter(EMRLabTurn Next, double Now);
};

/** One per eye: rotation of the eye (degrees, + to Frank's right / up) at curve values 0.25, 0.5, 0.75, 1.0. */
struct FMRLabEyeTable
{
	FName Curves[4];       // look right, left, up, down (CTRL_expressions_eyeLook*{L,R})
	float Degrees[4][4] = {}; // per curve, signed degrees at 0.25 .. 1.0 (yaw for right/left, pitch for up/down)
	float Neutral[2] = {};    // yaw, pitch of the eye with all curves at 0, in the head bone's frame
	/** Curve values for a direction in degrees (yaw + to the right, pitch + up), clamped 0..1. */
	void Solve(float Yaw, float Pitch, float OutValues[4]) const;
};

struct FMRLabGazeInput
{
	double Now = 0.0;
	float DeltaTime = 0.f;
	FVector FrankForward = FVector::XAxisVector; // the direction his face points at rest (horizontal)
	FVector FrankFeet = FVector::ZeroVector;     // actor location
	FTransform Head;                             // head bone, world
	FVector EyeL = FVector::ZeroVector;          // eye bones, world
	FVector EyeR = FVector::ZeroVector;
	bool bTracked = false;
	FVector Visitor = FVector::ZeroVector;       // tracked head point, world (valid when tracked)
	const FMRLabTurns* Turns = nullptr;
	float Arousal = 0.f;
	float Rapport = 0.f;
};

struct FMRLabGaze
{
	enum class EKind : uint8 { Visitor, Own, Aversion, Thinking, Glance };

	struct FRegion { FVector Min = FVector::ZeroVector; FVector Max = FVector::ZeroVector; float Weight = 1.f; };

	// Settings ("gaze" in Config/MRLabBehavior.json).
	TArray<FRegion> OwnRegions;      // Frank's own business: boxes of (forward, left, up) cm from his feet
	float NearDegrees = 20.f;        // the next own point is usually within about this angle of the current one
	float FarChance = 0.2f;          // ... except with this probability (anywhere)
	float EyeShiftBase = 0.08f;      // eye movement: seconds + seconds per degree, eased in and out
	float EyeShiftPerDegree = 0.006f;
	FVector2D WanderSpeed = { 10.f, 25.f };    // looking around: his attention glides between own points at these deg/s
	FVector2D WanderDwell = { 0.2f, 1.8f };    // ... and rests this long at each
	FVector2D EyeHopEvery = { 0.3f, 1.f };     // ... while the eyes hop to it, slightly ahead (EyeLead seconds of the glide)
	FVector2D EyeLead = { 0.2f, 0.5f };
	FVector2D JitterEvery = { 0.8f, 2.5f };    // small eye movements while he holds an aversion or a thought
	FVector2D JitterDegrees = { 0.5f, 2.f };
	FVector2D GlanceInterval = { 8.f, 20.f };
	FVector2D GlanceLength = { 0.5f, 2.f };
	FVector2D NoticeDelay = { 0.2f, 0.5f };
	float CloseDistance = 460.f;     // cm from Frank's eyes; closer (or moving fast) halves the glance interval
	float FastSpeed = 50.f;          // cm/s
	float ListenAversionEvery = 7.f; // mean seconds, x (1 + rapport)
	float ListenAversionLength = 1.1f;
	float SpeakAversionEvery = 4.8f;
	float SpeakAversionLength = 2.f;
	FVector2D AversionDegrees = { 8.f, 15.f };
	float PhraseStartAvert = 0.5f;   // probability of looking away at a phrase start
	FVector2D PhraseAvertLength = { 1.f, 2.f };
	float MinAversion = 1.f;         // seconds an aversion lasts before a phrase end can end it
	float ContinueSeconds = 1.5f;    // his voice back within this time after his turn seemed to end: the same turn
	float ThinkDelay = 0.6f;         // Frank silent this long after the visitor's turn: thinking aversion
	FVector2D ThinkAfterVoice = { 0.3f, 1.3f };
	FVector2D YieldHold = { 3.f, 5.f };
	FVector2D PauseGlanceEvery = { 3.f, 6.f };
	FVector2D PauseGlanceLength = { 0.5f, 1.5f };
	FVector2D ScanEvery = { 0.5f, 2.f };
	float HeadJoinDegrees = 20.f;
	float HeadDelay = 0.05f;
	float HeadSeconds = 0.9f;        // the head eases in and out and is 95 % there after this (two critically damped stages)
	FVector FallbackPoint = { 300.f, 0.f, 172.f }; // where a visitor is assumed when nobody is tracked (forward, left, up)
	FMRLabEyeTable Eyes[2];          // left, right

	void Load(const TSharedPtr<FJsonObject>& Object);
	void Update(const FMRLabGazeInput& In);

	// Output.
	float Curves[2][4] = {};         // per eye: look right, left, up, down
	FVector HeadTarget = FVector::ZeroVector;
	bool bHeadValid = false;
	EKind Kind = EKind::Own;
	float LastShiftDegrees = 0.f;    // amplitude of the latest saccade
	double LastShiftAt = -1e9;
	float YawPitch[2][2] = {};       // per eye, degrees (trace)
	FVector GazePoint = FVector::ZeroVector;

private:
	FVector Local(const FMRLabGazeInput& In, const FVector& Point) const; // (forward, left, up) -> world
	FVector VisitorPoint(const FMRLabGazeInput& In) const;
	FVector Offset(const FMRLabGazeInput& In, const FVector& Around, float Yaw, float Pitch) const;
	void LookAt(const FMRLabGazeInput& In, EKind NewKind, const FVector& Point, bool bTrackVisitor, double Until);
	void StartSaccade(const FMRLabGazeInput& In, const FVector& To);
	FVector RandomOwnPoint(const FMRLabGazeInput& In) const;
	void ChooseOwn(const FMRLabGazeInput& In);
	FVector WanderPoint(const FVector& Mid, double Time) const;

	bool bStarted = false;
	bool bWasTracked = false;
	EMRLabTurn LastTurn = EMRLabTurn::Outside;
	double Until = 0.0;              // end of the current fixation (own, glance, aversion)
	double NextAversion = 0.0;
	double NextGlance = 0.0;
	double NextScan = 0.0;
	double NoticeAt = -1.0;
	double ThinkUntil = -1.0;
	double AvertStart = -1e9;
	double SpeakingEndedAt = -1e9;   // when his last stretch of speaking ended
	double LastPhraseSeen = -1e9;
	// Looking around: his attention glides from one own point to the next; head and eyes follow it.
	bool bWander = false;
	FVector WanderFromDir = FVector::XAxisVector, WanderToDir = FVector::XAxisVector;
	float WanderFromDist = 300.f, WanderToDist = 300.f;
	double WanderStart = 0.0;
	float WanderSeconds = 1.f;
	double NextHop = 0.0;
	FVector Attention = FVector::ZeroVector;
	double NextJitter = 0.0;
	FVector Fixation = FVector::ZeroVector; // where the eyes go now (a waypoint, the target, or the target moved a little)
	FVector SaccadeEnd = FVector::ZeroVector;
	bool bTrackVisitor = false;      // the target follows the visitor
	FVector Scan = FVector::ZeroVector; // small offset on the visitor's face
	FVector Target = FVector::ZeroVector;
	// Saccade: from / to directions and distances from the eye midpoint at its start.
	FVector FromDir = FVector::XAxisVector, ToDir = FVector::XAxisVector;
	float FromDist = 300.f, ToDist = 300.f;
	double SaccadeStart = -1e9;
	float SaccadeSeconds = 0.f;
	// Head.
	FVector HeadAnchor = FVector::ZeroVector;
	bool bHeadInit = false;
	float HeadYaw = 0.f, HeadPitch = 0.f, HeadYawVel = 0.f, HeadPitchVel = 0.f, HeadDist = 300.f;
	float HeadYawA = 0.f, HeadPitchA = 0.f, HeadYawVelA = 0.f, HeadPitchVelA = 0.f; // first of the two stages
	bool bHeadFollowsVisitor = false;
	double HeadMoveAt = -1e9;
	FVector PendingAnchor = FVector::ZeroVector;
	bool bPendingFollowsVisitor = false;
	FVector LastVisitor = FVector::ZeroVector;
	float VisitorSpeed = 0.f;
};

struct FMRLabBlinks
{
	// Settings ("blinks" in Config/MRLabBehavior.json).
	float RestPerMinute = 17.f;
	float SpeakingPerMinute = 26.f;
	float MinInterval = 1.f;
	float CloseSeconds = 0.07f;
	float OpenSeconds = 0.18f;
	FVector2D LongClosed = { 0.4f, 0.6f };
	float ShiftDegrees = 25.f;
	float ShiftProbability = 0.5f;
	float UnderstoodProbability = 0.3f;
	float UnderstoodMinTurn = 2.f;
	float ModelGuard = 0.4f;
	float WaitForPause = 0.5f;
	float ArousalGain = 0.3f;

	void Load(const TSharedPtr<FJsonObject>& Object);
	/** ModelBlink: the lip sync model's own blink value now (max of both eyes). */
	void Update(double Now, const FMRLabTurns& Turns, const FMRLabGaze& Gaze, float ModelBlink, float Arousal);

	float Value = 0.f;     // own blink, both eyes
	int32 OwnCount = 0;
	int32 ModelCount = 0;
	bool bModelBlinking = false;

private:
	void Start(double Now, float Closed);
	void Schedule(double Now, float PerMinute);

	double NextAt = -1.0;
	double DueSince = -1.0;
	double LastBlink = -1e9;
	double BlinkStart = -1e9;
	float BlinkClosed = 0.f;
	double HandledShift = -1e9;
	EMRLabTurn LastTurn = EMRLabTurn::Outside;
};
