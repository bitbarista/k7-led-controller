package bridge

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/bitbarista/k7-led-controller/pc-bridge/internal/k7tcp"
)

//go:embed static/*.html static/vendor/* diagnostic/*.html presets.json
var staticFiles embed.FS

type Config struct {
	Host   string `json:"host"`
	Port   int    `json:"port"`
	Device string `json:"device"`
}

type State struct {
	Name                 string            `json:"name"`
	Mode                 string            `json:"mode"`
	Manual               []int             `json:"manual"`
	Schedule             [][]int           `json:"schedule"`
	ActivePreset         string            `json:"active_preset"`
	ScheduleShiftMinutes int               `json:"schedule_shift_minutes"`
	MasterBrightness     int               `json:"master_brightness"`
	LastReadAt           string            `json:"last_read_at,omitempty"`
	LastPushedAt         string            `json:"last_pushed_at,omitempty"`
	Extras               map[string]string `json:"extras,omitempty"`
}

type storeFile struct {
	Kind       string                     `json:"kind"`
	Schema     int                        `json:"schema"`
	Config     Config                     `json:"config"`
	State      State                      `json:"state"`
	Profiles   map[string]json.RawMessage `json:"profiles"`
	ExportedAt string                     `json:"exported_at,omitempty"`
}

type Server struct {
	mu         sync.RWMutex
	config     Config
	state      State
	profiles   map[string]json.RawMessage
	configPath string
	timeout    time.Duration
}

func NewServer(configPath string, timeout time.Duration) (*Server, error) {
	s := &Server{
		config: Config{
			Host:   k7tcp.DefaultHost,
			Port:   k7tcp.DefaultPort,
			Device: "k7mini",
		},
		state:      defaultState(),
		profiles:   map[string]json.RawMessage{},
		configPath: configPath,
		timeout:    timeout,
	}
	if err := s.loadStore(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Server) Config() Config {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.config
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleRoot)
	mux.Handle("/static/", http.StripPrefix("/static/", http.FileServer(http.FS(mustSub(staticFiles, "static")))))
	mux.Handle("/diagnostic/", http.StripPrefix("/diagnostic/", http.FileServer(http.FS(mustSub(staticFiles, "diagnostic")))))
	mux.HandleFunc("/diagnostic", func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, "/diagnostic/test.html", http.StatusFound)
	})
	mux.HandleFunc("/api/version", s.handleVersion)
	mux.HandleFunc("/api/capabilities", s.handleCapabilities)
	mux.HandleFunc("/api/config", s.handleConfig)
	mux.HandleFunc("/api/devices", s.handleDevices)
	mux.HandleFunc("/api/master", s.handleMaster)
	mux.HandleFunc("/api/lamp/read", s.handleLampRead)
	mux.HandleFunc("/api/state", s.handleState)
	mux.HandleFunc("/api/presets", s.handlePresets)
	mux.HandleFunc("/api/profiles", s.handleProfiles)
	mux.HandleFunc("/api/profiles/", s.handleProfileByName)
	mux.HandleFunc("/api/backup", s.handleBackup)
	mux.HandleFunc("/api/preview", s.handlePreview)
	mux.HandleFunc("/api/hand", s.handleHand)
	mux.HandleFunc("/api/push", s.handlePush)
	return withCORS(mux)
}

func (s *Server) client() k7tcp.Client {
	cfg := s.Config()
	return k7tcp.New(cfg.Host, cfg.Port, s.timeout)
}

func (s *Server) handleRoot(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	view := r.URL.Query().Get("view")
	ua := r.Header.Get("User-Agent")
	mobile := view == "mobile" || (view != "desktop" && (strings.Contains(ua, "Mobile") ||
		strings.Contains(ua, "Android") || strings.Contains(ua, "iPhone") ||
		strings.Contains(ua, "iPad")))
	if mobile {
		http.Redirect(w, r, "/static/mobile.html", http.StatusFound)
		return
	}
	http.Redirect(w, r, "/static/", http.StatusFound)
}

func mustSub(fsys fs.FS, dir string) fs.FS {
	sub, err := fs.Sub(fsys, dir)
	if err != nil {
		panic(err)
	}
	return sub
}

func (s *Server) handleVersion(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"bridge":    "pc-bridge",
		"platform":  "pc_bridge",
		"transport": "direct_lamp",
	})
}

func (s *Server) handleCapabilities(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"platform":  "pc_bridge",
		"transport": "direct_lamp",
		"capabilities": map[string]any{
			"read_lamp":                   true,
			"push_schedule":               true,
			"manual_preview":              true,
			"profiles":                    true,
			"community_presets":           true,
			"backup_restore":              true,
			"fixed_lunar":                 true,
			"siesta_baked_schedule":       true,
			"smooth_ramp":                 false,
			"tracked_lunar":               false,
			"acclimation":                 false,
			"seasonal_daylength":          false,
			"feed_mode":                   false,
			"maintenance_mode":            false,
			"setup_portal":                false,
			"logs":                        false,
			"persistent_controller_clock": false,
		},
	})
}

func (s *Server) handleConfig(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		writeJSON(w, http.StatusOK, s.Config())
	case http.MethodPost:
		var in Config
		if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
			writeError(w, http.StatusBadRequest, "Bad JSON")
			return
		}
		s.mu.Lock()
		if strings.TrimSpace(in.Host) != "" {
			s.config.Host = strings.TrimSpace(in.Host)
		}
		if in.Port > 0 && in.Port <= 65535 {
			s.config.Port = in.Port
		}
		if in.Device == "k7mini" || in.Device == "k7pro" {
			s.config.Device = in.Device
		}
		cfg := s.config
		s.mu.Unlock()

		if err := s.saveStore(); err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("Save config failed: %v", err))
			return
		}
		writeJSON(w, http.StatusOK, cfg)
	default:
		methodNotAllowed(w)
	}
}

func (s *Server) handleDevices(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"k7mini": map[string]any{
			"label":    "K7 Mini",
			"channels": []string{"white", "royal_blue", "blue"},
		},
		"k7pro": map[string]any{
			"label":    "K7 Pro",
			"channels": []string{"white", "royal_blue", "green", "uv", "cyan", "red"},
		},
	})
}

func (s *Server) handleMaster(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		s.mu.RLock()
		value := s.state.MasterBrightness
		s.mu.RUnlock()
		if value <= 0 {
			value = 100
		}
		writeJSON(w, http.StatusOK, map[string]int{"value": value})
	case http.MethodPost:
		var in struct {
			Value int `json:"value"`
		}
		if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
			writeError(w, http.StatusBadRequest, "Bad JSON")
			return
		}
		value := clamp(in.Value, 0, 200)
		s.mu.Lock()
		s.state.MasterBrightness = value
		s.mu.Unlock()
		if err := s.saveStore(); err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("Save state failed: %v", err))
			return
		}
		writeJSON(w, http.StatusOK, map[string]int{"value": value})
	default:
		methodNotAllowed(w)
	}
}

func (s *Server) handleLampRead(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	state, err := s.client().ReadAll()
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	if err := s.saveStateFromLamp(state, true, false); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("Save state failed: %v", err))
		return
	}
	writeJSON(w, http.StatusOK, state)
}

func (s *Server) handleState(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	s.mu.RLock()
	state := s.state
	s.mu.RUnlock()
	writeJSON(w, http.StatusOK, state)
}

func (s *Server) handlePresets(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	presets, err := staticFiles.ReadFile("presets.json")
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("Load presets failed: %v", err))
		return
	}
	var catalog map[string]json.RawMessage
	if err := json.Unmarshal(presets, &catalog); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("Parse presets failed: %v", err))
		return
	}
	s.mu.RLock()
	device := s.config.Device
	s.mu.RUnlock()
	if device == "" {
		device = "k7mini"
	}
	payload, ok := catalog[device]
	if !ok {
		payload = catalog["k7mini"]
	}
	writeRawJSON(w, http.StatusOK, payload)
}

func (s *Server) handleProfiles(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		s.mu.RLock()
		profiles := cloneProfiles(s.profiles)
		s.mu.RUnlock()
		writeJSON(w, http.StatusOK, profiles)
	case http.MethodPost:
		var raw json.RawMessage
		if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
			writeError(w, http.StatusBadRequest, "Bad JSON")
			return
		}
		var probe struct {
			Name string `json:"name"`
		}
		if err := json.Unmarshal(raw, &probe); err != nil {
			writeError(w, http.StatusBadRequest, "Bad JSON")
			return
		}
		name := strings.TrimSpace(probe.Name)
		if name == "" {
			writeError(w, http.StatusBadRequest, "Name required")
			return
		}
		s.mu.Lock()
		s.profiles[name] = raw
		s.mu.Unlock()
		if err := s.saveStore(); err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("Save profiles failed: %v", err))
			return
		}
		writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
	default:
		methodNotAllowed(w)
	}
}

func (s *Server) handleProfileByName(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodDelete {
		methodNotAllowed(w)
		return
	}
	name, err := url.PathUnescape(strings.TrimPrefix(r.URL.Path, "/api/profiles/"))
	if err != nil || strings.TrimSpace(name) == "" {
		writeError(w, http.StatusBadRequest, "Profile name required")
		return
	}
	s.mu.Lock()
	delete(s.profiles, name)
	s.mu.Unlock()
	if err := s.saveStore(); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("Save profiles failed: %v", err))
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func (s *Server) handleBackup(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		backup := s.snapshotStore()
		backup.Kind = "k7_pc_bridge_backup"
		backup.ExportedAt = time.Now().Format(time.RFC3339)
		w.Header().Set("Content-Disposition", `attachment; filename="k7-pc-bridge-backup.json"`)
		writeJSON(w, http.StatusOK, backup)
	case http.MethodPost:
		var backup storeFile
		if err := json.NewDecoder(r.Body).Decode(&backup); err != nil {
			writeError(w, http.StatusBadRequest, "Bad JSON")
			return
		}
		if backup.Kind != "k7_pc_bridge_backup" || backup.Schema != 1 {
			writeError(w, http.StatusBadRequest, "Unsupported backup format")
			return
		}
		if backup.Profiles == nil {
			backup.Profiles = map[string]json.RawMessage{}
		}
		normalizeConfig(&backup.Config)
		normalizeState(&backup.State)
		s.mu.Lock()
		s.config = backup.Config
		s.state = backup.State
		s.profiles = cloneProfiles(backup.Profiles)
		s.mu.Unlock()
		if err := s.saveStore(); err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("Save backup failed: %v", err))
			return
		}
		writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
	default:
		methodNotAllowed(w)
	}
}

func (s *Server) handlePreview(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	ch, err := decodeChannels(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err := s.client().PreviewBrightness(ch); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func (s *Server) handleHand(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}
	ch, err := decodeChannels(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if err := s.client().HandLuminance(ch); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	if err := s.saveManualState(ch); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("Save state failed: %v", err))
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func (s *Server) handlePush(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		methodNotAllowed(w)
		return
	}

	var in struct {
		Manual   []int   `json:"manual"`
		Schedule [][]int `json:"schedule"`
		Mode     string  `json:"mode"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		writeError(w, http.StatusBadRequest, "Bad JSON")
		return
	}

	manual, err := normalizeManual(in.Manual)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	schedule, err := normalizeSchedule(in.Schedule)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	autoMode := in.Mode != "manual"

	s.mu.RLock()
	master := s.state.MasterBrightness
	s.mu.RUnlock()
	manualForLamp, scheduleForLamp := applyMasterToLampState(manual, schedule, master)

	if err := s.client().PushSchedule(manualForLamp, scheduleForLamp, autoMode); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	if err := s.savePushedState(manualForLamp, scheduleForLamp, autoMode); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("Save state failed: %v", err))
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func (s *Server) loadStore() error {
	data, err := os.ReadFile(s.configPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}

	if _, ok := raw["config"]; ok {
		var store storeFile
		if err := json.Unmarshal(data, &store); err != nil {
			return err
		}
		normalizeConfig(&store.Config)
		normalizeState(&store.State)
		s.config = store.Config
		s.state = store.State
		if store.Profiles != nil {
			s.profiles = cloneProfiles(store.Profiles)
		}
		return nil
	}

	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return err
	}
	normalizeConfig(&cfg)
	s.config = cfg
	return nil
}

func (s *Server) saveStore() error {
	store := s.snapshotStore()
	data, err := json.MarshalIndent(store, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.configPath, append(data, '\n'), 0644)
}

func (s *Server) snapshotStore() storeFile {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return storeFile{
		Kind:     "k7_pc_bridge_store",
		Schema:   1,
		Config:   s.config,
		State:    s.state,
		Profiles: cloneProfiles(s.profiles),
	}
}

func (s *Server) saveStateFromLamp(lamp k7tcp.LampState, read bool, pushed bool) error {
	mode := "manual"
	if lamp.AutoMode {
		mode = "auto"
	}
	state := State{
		Name:                 lamp.Name,
		Mode:                 mode,
		Manual:               intsFromManual(lamp.Manual),
		Schedule:             intsFromSchedule(lamp.Schedule),
		ScheduleShiftMinutes: 0,
		MasterBrightness:     100,
	}
	now := time.Now().Format(time.RFC3339)
	if read {
		state.LastReadAt = now
	}
	if pushed {
		state.LastPushedAt = now
	}
	s.mu.Lock()
	state.ActivePreset = s.state.ActivePreset
	if !pushed {
		state.LastPushedAt = s.state.LastPushedAt
	}
	s.state = state
	s.mu.Unlock()
	return s.saveStore()
}

func (s *Server) saveManualState(ch [k7tcp.Channels]uint8) error {
	s.mu.Lock()
	s.state.Mode = "manual"
	s.state.Manual = intsFromChannels(ch)
	s.mu.Unlock()
	return s.saveStore()
}

func (s *Server) savePushedState(manual [k7tcp.Channels]uint8, schedule [k7tcp.Slots][8]uint8, autoMode bool) error {
	mode := "manual"
	if autoMode {
		mode = "auto"
	}
	s.mu.Lock()
	s.state.Mode = mode
	s.state.Manual = intsFromChannels(manual)
	s.state.Schedule = intsFromUintSchedule(schedule)
	s.state.LastPushedAt = time.Now().Format(time.RFC3339)
	s.mu.Unlock()
	return s.saveStore()
}

func decodeChannels(r *http.Request) ([k7tcp.Channels]uint8, error) {
	var in struct {
		Channels []int `json:"channels"`
	}
	if err := json.NewDecoder(r.Body).Decode(&in); err != nil {
		return [k7tcp.Channels]uint8{}, fmt.Errorf("Bad JSON")
	}
	return normalizeManual(in.Channels)
}

func normalizeManual(values []int) ([k7tcp.Channels]uint8, error) {
	var out [k7tcp.Channels]uint8
	if len(values) == 0 {
		return out, fmt.Errorf("manual/channels required")
	}
	for i := 0; i < len(values) && i < k7tcp.Channels; i++ {
		if values[i] < 0 || values[i] > 100 {
			return out, fmt.Errorf("channel %d out of range 0-100", i)
		}
		out[i] = uint8(values[i])
	}
	return out, nil
}

func normalizeSchedule(values [][]int) ([k7tcp.Slots][8]uint8, error) {
	var out [k7tcp.Slots][8]uint8
	if len(values) != k7tcp.Slots {
		return out, fmt.Errorf("schedule must contain exactly %d rows", k7tcp.Slots)
	}
	for h, row := range values {
		if len(row) < 8 {
			return out, fmt.Errorf("schedule row %d must contain hour, minute, and six channels", h)
		}
		for i := 0; i < 8; i++ {
			if row[i] < 0 || row[i] > 100 {
				return out, fmt.Errorf("schedule row %d value %d out of range 0-100", h, i)
			}
			out[h][i] = uint8(row[i])
		}
		if out[h][0] > 23 || out[h][1] > 59 {
			return out, fmt.Errorf("schedule row %d has invalid time", h)
		}
	}
	return out, nil
}

func applyMasterToLampState(manual [k7tcp.Channels]uint8, schedule [k7tcp.Slots][8]uint8, master int) ([k7tcp.Channels]uint8, [k7tcp.Slots][8]uint8) {
	if master <= 0 {
		master = 0
	}
	if master == 100 {
		return manual, schedule
	}
	var scaledManual [k7tcp.Channels]uint8
	var scaledSchedule [k7tcp.Slots][8]uint8
	for i := 0; i < k7tcp.Channels; i++ {
		scaledManual[i] = scalePercent(manual[i], master)
	}
	for h := 0; h < k7tcp.Slots; h++ {
		scaledSchedule[h][0] = schedule[h][0]
		scaledSchedule[h][1] = schedule[h][1]
		for c := 2; c < 8; c++ {
			scaledSchedule[h][c] = scalePercent(schedule[h][c], master)
		}
	}
	return scaledManual, scaledSchedule
}

func scalePercent(value uint8, master int) uint8 {
	scaled := int(value)*master + 50
	scaled /= 100
	if scaled < 0 {
		return 0
	}
	if scaled > 100 {
		return 100
	}
	return uint8(scaled)
}

func defaultState() State {
	return State{
		Name:                 "",
		Mode:                 "auto",
		Manual:               make([]int, k7tcp.Channels),
		Schedule:             defaultSchedule(),
		ScheduleShiftMinutes: 0,
		MasterBrightness:     100,
	}
}

func defaultSchedule() [][]int {
	out := make([][]int, k7tcp.Slots)
	for h := 0; h < k7tcp.Slots; h++ {
		out[h] = []int{h, 0, 0, 0, 0, 0, 0, 0}
	}
	return out
}

func normalizeConfig(cfg *Config) {
	if strings.TrimSpace(cfg.Host) == "" {
		cfg.Host = k7tcp.DefaultHost
	}
	if cfg.Port <= 0 || cfg.Port > 65535 {
		cfg.Port = k7tcp.DefaultPort
	}
	if cfg.Device != "k7mini" && cfg.Device != "k7pro" {
		cfg.Device = "k7mini"
	}
}

func normalizeState(state *State) {
	if state.Mode != "manual" {
		state.Mode = "auto"
	}
	if len(state.Manual) == 0 {
		state.Manual = make([]int, k7tcp.Channels)
	}
	for len(state.Manual) < k7tcp.Channels {
		state.Manual = append(state.Manual, 0)
	}
	if len(state.Manual) > k7tcp.Channels {
		state.Manual = state.Manual[:k7tcp.Channels]
	}
	for i := range state.Manual {
		state.Manual[i] = clamp(state.Manual[i], 0, 100)
	}
	if len(state.Schedule) != k7tcp.Slots {
		state.Schedule = defaultSchedule()
	}
	for h := 0; h < k7tcp.Slots; h++ {
		if len(state.Schedule[h]) < 8 {
			state.Schedule[h] = []int{h, 0, 0, 0, 0, 0, 0, 0}
		}
		state.Schedule[h] = state.Schedule[h][:8]
		state.Schedule[h][0] = clamp(state.Schedule[h][0], 0, 23)
		state.Schedule[h][1] = clamp(state.Schedule[h][1], 0, 59)
		for i := 2; i < 8; i++ {
			state.Schedule[h][i] = clamp(state.Schedule[h][i], 0, 100)
		}
	}
	state.ScheduleShiftMinutes = 0
	if state.MasterBrightness <= 0 {
		state.MasterBrightness = 100
	}
}

func clamp(v int, min int, max int) int {
	if v < min {
		return min
	}
	if v > max {
		return max
	}
	return v
}

func cloneProfiles(in map[string]json.RawMessage) map[string]json.RawMessage {
	out := make(map[string]json.RawMessage, len(in))
	for k, v := range in {
		out[k] = append(json.RawMessage(nil), v...)
	}
	return out
}

func intsFromManual(in [k7tcp.Channels]int) []int {
	out := make([]int, k7tcp.Channels)
	for i := range out {
		out[i] = in[i]
	}
	return out
}

func intsFromChannels(in [k7tcp.Channels]uint8) []int {
	out := make([]int, k7tcp.Channels)
	for i := range out {
		out[i] = int(in[i])
	}
	return out
}

func intsFromSchedule(in [k7tcp.Slots][8]int) [][]int {
	out := make([][]int, k7tcp.Slots)
	for h := range out {
		out[h] = make([]int, 8)
		for i := range out[h] {
			out[h][i] = in[h][i]
		}
	}
	return out
}

func intsFromUintSchedule(in [k7tcp.Slots][8]uint8) [][]int {
	out := make([][]int, k7tcp.Slots)
	for h := range out {
		out[h] = make([]int, 8)
		for i := range out[h] {
			out[h][i] = int(in[h][i])
		}
	}
	return out
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeRawJSON(w http.ResponseWriter, status int, value []byte) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(value)
}

func writeText(w http.ResponseWriter, status int, value string) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(status)
	_, _ = w.Write([]byte(value))
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]any{"ok": false, "error": message})
}

func methodNotAllowed(w http.ResponseWriter) {
	writeError(w, http.StatusMethodNotAllowed, "Method not allowed")
}

func withCORS(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "http://127.0.0.1:8787")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}
