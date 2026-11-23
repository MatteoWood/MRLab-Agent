#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "MRLabGaze.h"

// Frank's body (README 4.15, Step 9D), owned and fed by UMRLabBehaviorComponent. Plain structs, game thread.

/** Posture by conversation state: the chest turns towards the visitor and leans, and a low mood lowers head and chest.
 * The MRLab Life node applies it to the spine only, so the feet stay where the idle clip puts them. */
struct FMRLabPosture
{
	// Settings ("posture" in Config/MRLabBehavior.json).
	FString BodyAnim;            // AnimBP class put on the body when Play starts (outside Play he keeps the A-pose, D130)
	float ChestShare = 0.25f;    // in a conversation the chest turns this share of the visitor's direction ...
	float ChestMax = 12.f;       // ... at most this far (degrees)
	float ListenLean = 2.f;      // forward lean while the visitor speaks and while he thinks (degrees)
	float Seconds = 2.f;         // changes are 95 % there after this (two critically damped stages)
	float LowerPerValence = 4.f; // valence below the persona baseline lowers head and chest by this many degrees per unit ...
	float LowerMax = 2.f;        // ... at most this far

	void Load(const TSharedPtr<FJsonObject>& Object);
	/** VisitorYaw: the visitor's direction from his feet (degrees, + to his right as UE yaw); ValenceDrop: how far the
	 * slow mood's valence is below the persona baseline (0 or more). */
	void Update(float DeltaTime, EMRLabTurn State, float VisitorYaw, float ValenceDrop);

	// Output (eased).
	float ChestYaw = 0.f;  // degrees, UE yaw
	float Lean = 0.f;      // degrees forward
	float Lower = 0.f;     // degrees down, chest and head

private:
	float YawA = 0.f, YawVA = 0.f, YawV = 0.f;
	float LeanA = 0.f, LeanVA = 0.f, LeanV = 0.f;
	float LowerA = 0.f, LowerVA = 0.f, LowerV = 0.f;
};

/** Silent listening nods (Step 9E, D133), by Ward's rule on the visitor's pitch: a stretch of their voice in the lowest
 * quarter of their own pitch range, after enough of their turn, is answered by a nod a little later. */
struct FMRLabListening
{
	// Settings ("listening" in Config/MRLabBehavior.json).
	float LowShare = 0.26f;    // low pitch: below this share of the visitor's own voiced pitch (the last 30 s of it) ...
	float LowSeconds = 0.11f;  // ... for at least this long (10 ms frames; a single unvoiced or higher frame is bridged)
	float MinSpeech = 0.7f;    // only this long into their turn
	float Delay = 0.7f;        // the nod comes this long after the cue
	float MinGap = 2.5f;       // nods at least this far apart (start to start) ...
	float PerMinute = 10.f;    // ... and at most this many in a minute
	float MinVoiced = 2.f;     // seconds of their voiced speech before their pitch range counts
	float Degrees = 3.f;       // head target degrees down (the head turns about 70 % of it)
	float Down = 0.2f;         // seconds down, then
	float Up = 0.3f;           // seconds back up
	float DoubleChance = 0.33f; // a second nod, this often ...
	float DoubleAfter = 0.5f;  // ... starting this long after the first ...
	float DoubleSize = 0.7f;   // ... this much smaller
	float ConcernSlow = 1.7f;  // while he shows concern: this many times slower ...
	float ConcernSize = 0.7f;  // ... and this much smaller

	void Load(const TSharedPtr<FJsonObject>& Object);
	/** Frames: the visitor's pitch frames of this tick (Hz, 0 unvoiced; RMS). bVisitorVoice: they are speaking (their
	 * frames count for their pitch range); bCue: a cue may start a nod (listening, his voice not heard, no veto);
	 * bNod: a due nod may still happen (his voice not heard); TurnAge: seconds into their turn. */
	void Update(double Now, const TArray<FVector2f>& Frames, bool bVisitorVoice, bool bCue, bool bNod, float TurnAge, bool bConcerned);
	/** A nod at this time (a held listening sound starts playing, D128). */
	void NodAt(double At) { PendingAt = At; bPendingForced = true; }

	// Output.
	float Pitch = 0.f;   // head target degrees down now
	int32 Count = 0;     // nods
	int32 Cues = 0;      // cues found (also those that gave no nod)
	float LowHz = 0.f;   // the visitor's low-pitch limit now
	float LastHz = 0.f;  // their latest voiced pitch

private:
	struct FNod { double Start; float Size; float DownS; float UpS; };
	void Start(double At, bool bConcerned);
	TArray<float> Voiced;   // their recent voiced pitch (ring)
	int32 VoicedNext = 0;
	double LowAt = -1e9;    // when LowHz was last computed
	int32 LowRun = 0;       // low frames in the current stretch
	int32 Bridge = 0;       // frames bridged in it
	bool bStretchUsed = false;
	double PendingAt = -1.0;
	bool bPendingForced = false;
	TArray<double> Starts;  // nod starts (the last minute)
	TArray<FNod> Active;
};

/** Small nods on the stressed syllables of his own voice: a loudness peak of the voice about to be heard starts a nod
 * whose lowest point comes with the peak. Only while his voice is heard (listening nods are 9E). */
struct FMRLabNods
{
	// Settings ("nods" in Config/MRLabBehavior.json).
	float Lead = 0.1f;       // seconds ahead of the playhead at which his voice is read (the nod reaches its low point then)
	float Down = 0.12f;      // seconds down, then
	float Up = 0.18f;        // seconds back up
	float MinGap = 0.4f;     // seconds between nod starts at least
	float Peak = 1.3f;       // a peak must be this many times the running mean of his loudness ...
	float MinLevel = 0.02f;  // ... and at least this loud (RMS)
	float MeanSeconds = 2.f; // the running mean of his loudness (while he speaks) over about this long
	float Base = 1.f;        // degrees for a peak just above the threshold ...
	float Top = 2.f;         // ... up to this for a peak twice the threshold
	float EmphasisTop = 3.f; // degrees at full emphasis (Decisions strength 3 on the words heard)
	float ArousalGain = 0.5f; // an excited slow mood makes the nods up to (1 + this) times larger

	void Load(const TSharedPtr<FJsonObject>& Object);
	/** Level: RMS of his voice Lead s ahead; bHeard: his voice is heard now; Emphasis 0..1; ArousalUp 0..1. */
	void Update(double Now, float DeltaTime, float Level, bool bHeard, float Emphasis, float ArousalUp);

	// Output.
	float Pitch = 0.f;   // degrees down now
	int32 Count = 0;

private:
	float Prev[2] = {};  // the two previous levels
	float Mean = 0.f;
	double LastStart = -1e9;
	double Start = -1e9;
	float Amplitude = 0.f;
};
