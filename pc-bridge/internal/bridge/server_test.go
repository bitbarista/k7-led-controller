package bridge

import (
	"path/filepath"
	"testing"

	"github.com/bitbarista/k7-led-controller/pc-bridge/internal/k7tcp"
)

func TestApplyMasterToLampStateScalesManualAndSchedule(t *testing.T) {
	var manual [k7tcp.Channels]uint8
	manual[0], manual[1], manual[2] = 25, 50, 100

	var schedule [k7tcp.Slots][8]uint8
	schedule[12] = [8]uint8{12, 0, 25, 50, 100, 0, 1, 99}

	scaledManual, scaledSchedule := applyMasterToLampState(manual, schedule, 8)

	if got, want := scaledManual, ([k7tcp.Channels]uint8{2, 4, 8, 0, 0, 0}); got != want {
		t.Fatalf("manual = %v, want %v", got, want)
	}
	if got, want := scaledSchedule[12], ([8]uint8{12, 0, 2, 4, 8, 0, 0, 8}); got != want {
		t.Fatalf("schedule row = %v, want %v", got, want)
	}
}

func TestApplyMasterToLampStateClampsAbove100(t *testing.T) {
	var manual [k7tcp.Channels]uint8
	manual[0], manual[1] = 60, 100

	var schedule [k7tcp.Slots][8]uint8
	schedule[9] = [8]uint8{9, 0, 60, 100, 1, 0, 0, 0}

	scaledManual, scaledSchedule := applyMasterToLampState(manual, schedule, 200)

	if got, want := scaledManual[0], uint8(100); got != want {
		t.Fatalf("manual[0] = %d, want %d", got, want)
	}
	if got, want := scaledManual[1], uint8(100); got != want {
		t.Fatalf("manual[1] = %d, want %d", got, want)
	}
	if got, want := scaledSchedule[9], ([8]uint8{9, 0, 100, 100, 2, 0, 0, 0}); got != want {
		t.Fatalf("schedule row = %v, want %v", got, want)
	}
}

func TestBakePCBridgeEffectsAppliesSiestaAndFixedLunar(t *testing.T) {
	var schedule [k7tcp.Slots][8]uint8
	for h := 0; h < k7tcp.Slots; h++ {
		schedule[h] = [8]uint8{uint8(h), 0, 40, 40, 40, 0, 0, 0}
	}
	schedule[0] = [8]uint8{0, 0, 0, 0, 0, 0, 0, 0}
	schedule[13] = [8]uint8{13, 0, 80, 60, 40, 0, 0, 0}

	out := bakePCBridgeEffects(
		schedule,
		SiestaConfig{Enabled: true, Start: "13:00", Duration: 60, Intensity: 25},
		LunarConfig{Enabled: true, Start: "18:00", End: "06:00", MaxIntensity: 15, DayThreshold: 2},
	)

	if got, want := out[13], ([8]uint8{13, 0, 60, 45, 30, 0, 0, 0}); got != want {
		t.Fatalf("siesta row = %v, want %v", got, want)
	}
	if got, want := out[0][3], uint8(15); got != want {
		t.Fatalf("lunar royal blue = %d, want %d", got, want)
	}
	if got, want := out[0][6], uint8(11); got != want {
		t.Fatalf("lunar cyan = %d, want %d", got, want)
	}
	if got, want := out[12][3], uint8(40); got != want {
		t.Fatalf("daylight royal blue = %d, want %d", got, want)
	}
}

func TestSavePushedDinoPresetDisablesLunar(t *testing.T) {
	s, err := NewServer(filepath.Join(t.TempDir(), "store.json"), 100)
	if err != nil {
		t.Fatal(err)
	}
	s.state.Lunar = LunarConfig{Enabled: true, Active: true, MaxIntensity: 15}

	var manual [k7tcp.Channels]uint8
	var schedule [k7tcp.Slots][8]uint8
	if err := s.savePushedState(manual, schedule, true, "preset:dino", true); err != nil {
		t.Fatal(err)
	}

	if s.state.Lunar.Enabled || s.state.Lunar.Active {
		t.Fatalf("lunar = %+v, want disabled", s.state.Lunar)
	}
	if got, want := s.state.ActivePreset, "preset:dino"; got != want {
		t.Fatalf("active preset = %q, want %q", got, want)
	}
}

func TestReadLampStateKeepsDefaultScheduleModeWhenLampReportsManual(t *testing.T) {
	s, err := NewServer(filepath.Join(t.TempDir(), "store.json"), 100)
	if err != nil {
		t.Fatal(err)
	}

	var lamp k7tcp.LampState
	lamp.AutoMode = false

	if err := s.saveStateFromLamp(lamp, true, false); err != nil {
		t.Fatal(err)
	}

	if got, want := s.state.Mode, "auto"; got != want {
		t.Fatalf("mode = %q, want %q", got, want)
	}
}

func TestReadLampStatePreservesDeliberateManualMode(t *testing.T) {
	s, err := NewServer(filepath.Join(t.TempDir(), "store.json"), 100)
	if err != nil {
		t.Fatal(err)
	}
	s.state.Mode = "manual"

	var lamp k7tcp.LampState
	lamp.AutoMode = false

	if err := s.saveStateFromLamp(lamp, true, false); err != nil {
		t.Fatal(err)
	}

	if got, want := s.state.Mode, "manual"; got != want {
		t.Fatalf("mode = %q, want %q", got, want)
	}
}
