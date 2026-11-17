# Builds the scripted visitor for repeatable Live API tests (24 kHz mono 16 bit WAV for TestInputWav, README 4.13).
# Usage: powershell -File Tools/make_visitor_audio.ps1 -Out Saved/BehaviorTest/visitor_script.wav
param([string]$Out)
Add-Type -AssemblyName System.Speech
$lines = @(
  "Hello! Are you the guy who runs this wall?",
  "I just got accepted into the master's program here. I'm so happy!",
  "How many cameras track people in this room?",
  "My cat knocked my laptop off the table this morning, and the screen cracked.",
  "Honestly, I think LED walls are just big TVs. Nothing special.",
  "Can you lift your right arm?",
  "Now do a backflip!",
  "That was hilarious. You're funnier than my professor.",
  "My grandmother passed away last week.",
  "So I was walking here this morning and",
  "the door to the lab would not open, so I climbed through the window.",
  "Wait, you can see me? What color is my shirt?",
  "I kicked one of the wall panels by accident earlier. Sorry.",
  "Shut up, you stupid robot.",
  "Sorry, I didn't mean that. Long day.",
  "Can you wave at my friend over there?",
  "What is the refresh rate of this wall?",
  "I think the cameras use lidar, right?",
  "Do you ever get bored standing there all day?",
  "Put your arm down, please.",
  "Tell me a joke about technicians.",
  "I once poured coffee into a server rack. It still smells.",
  "Is it true that you have worked here for forty years?",
  "Could you cross your arms like a grumpy old man?",
  "My friend says you are just a recording.",
  "What would you change about this lab if you could?",
  "I failed my exam yesterday. I studied for weeks.",
  "But my professor said I can retake it next month!",
  "Can you jump?",
  "What do you think about virtual reality headsets?",
  "Thanks for your help, Frank. See you tomorrow."
)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice("Microsoft Zira Desktop")
$pcm = New-Object System.IO.MemoryStream
$gap = New-Object byte[] (24000 * 2 * 16)   # 16 s for Frank's answer
$short = New-Object byte[] (24000 * 2 * 2)  # 2 s pause inside an unfinished sentence
$pcm.Write((New-Object byte[] (24000 * 2 * 3)), 0, 24000 * 2 * 3)
for ($i = 0; $i -lt $lines.Count; $i++) {
  $ms = New-Object System.IO.MemoryStream
  $synth.SetOutputToAudioStream($ms, $fmt)
  $synth.Speak($lines[$i])
  $synth.SetOutputToNull()
  $bytes = $ms.ToArray()
  $pcm.Write($bytes, 0, $bytes.Length)
  if ($lines[$i].EndsWith("and")) { $pcm.Write($short, 0, $short.Length) } else { $pcm.Write($gap, 0, $gap.Length) }
}
$data = $pcm.ToArray()
$w = New-Object System.IO.BinaryWriter([System.IO.File]::Create($Out))
$w.Write([Text.Encoding]::ASCII.GetBytes("RIFF")); $w.Write([int](36 + $data.Length)); $w.Write([Text.Encoding]::ASCII.GetBytes("WAVE"))
$w.Write([Text.Encoding]::ASCII.GetBytes("fmt ")); $w.Write([int]16); $w.Write([int16]1); $w.Write([int16]1); $w.Write([int]24000); $w.Write([int]48000); $w.Write([int16]2); $w.Write([int16]16)
$w.Write([Text.Encoding]::ASCII.GetBytes("data")); $w.Write([int]$data.Length); $w.Write($data)
$w.Close()
"{0:N1} s, {1} lines" -f ($data.Length / 48000), $lines.Count
