package bridge

import (
	"embed"
	"encoding/json"
	"fmt"
	"io/fs"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/bitbarista/k7-led-controller/pc-bridge/internal/k7tcp"
)

//go:embed static/*.html
var staticFiles embed.FS

type Config struct {
	Host   string `json:"host"`
	Port   int    `json:"port"`
	Device string `json:"device"`
}

type Server struct {
	mu         sync.RWMutex
	config     Config
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
		configPath: configPath,
		timeout:    timeout,
	}
	if err := s.loadConfig(); err != nil {
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
	mux.HandleFunc("/api/version", s.handleVersion)
	mux.HandleFunc("/api/capabilities", s.handleCapabilities)
	mux.HandleFunc("/api/config", s.handleConfig)
	mux.HandleFunc("/api/devices", s.handleDevices)
	mux.HandleFunc("/api/lamp/read", s.handleLampRead)
	mux.HandleFunc("/api/state", s.handleState)
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
	http.Redirect(w, r, "/static/test.html", http.StatusFound)
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

		if err := s.saveConfig(); err != nil {
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
	writeJSON(w, http.StatusOK, state)
}

func (s *Server) handleState(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		methodNotAllowed(w)
		return
	}
	state, err := s.client().ReadAll()
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	mode := "manual"
	if state.AutoMode {
		mode = "auto"
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"name":     state.Name,
		"mode":     mode,
		"manual":   state.Manual,
		"schedule": state.Schedule,
	})
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

	if err := s.client().PushSchedule(manual, schedule, autoMode); err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"ok": true})
}

func (s *Server) loadConfig() error {
	data, err := os.ReadFile(s.configPath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}
	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return err
	}
	if strings.TrimSpace(cfg.Host) != "" {
		s.config.Host = strings.TrimSpace(cfg.Host)
	}
	if cfg.Port > 0 && cfg.Port <= 65535 {
		s.config.Port = cfg.Port
	}
	if cfg.Device == "k7mini" || cfg.Device == "k7pro" {
		s.config.Device = cfg.Device
	}
	return nil
}

func (s *Server) saveConfig() error {
	cfg := s.Config()
	data, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.configPath, append(data, '\n'), 0644)
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

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
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
