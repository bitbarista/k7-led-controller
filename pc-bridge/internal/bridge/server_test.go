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
