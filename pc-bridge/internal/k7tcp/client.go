package k7tcp

import (
	"errors"
	"fmt"
	"io"
	"net"
	"strings"
	"time"
)

const (
	Channels = 6
	Slots    = 24

	DefaultHost = "192.168.4.1"
	DefaultPort = 8266
)

var (
	pktStart  = []byte{0xaa, 0xa5}
	pktEnd    = byte(0xbb)
	respMagic = []byte{0xab, 0xaa}

	cmdSyncTime         = [2]byte{0x10, 0x03}
	cmdChangeMode       = [2]byte{0x10, 0x04}
	cmdHandLuminance    = [2]byte{0x10, 0x05}
	cmdPreviewLuminance = [2]byte{0x10, 0x06}
	cmdAllSet           = [2]byte{0x10, 0x07}
	cmdAllRead          = [2]byte{0x10, 0x08}
)

type Client struct {
	Host    string
	Port    int
	Timeout time.Duration
}

type LampState struct {
	Name     string        `json:"name"`
	AutoMode bool          `json:"auto_mode"`
	Manual   [Channels]int `json:"manual"`
	Schedule [Slots][8]int `json:"schedule"`
	Valid    bool          `json:"valid"`
}

func New(host string, port int, timeout time.Duration) Client {
	if strings.TrimSpace(host) == "" {
		host = DefaultHost
	}
	if port == 0 {
		port = DefaultPort
	}
	if timeout <= 0 {
		timeout = 500 * time.Millisecond
	}
	return Client{Host: host, Port: port, Timeout: timeout}
}

func (c Client) ReadAll() (LampState, error) {
	conn, err := c.connect()
	if err != nil {
		return LampState{}, err
	}
	defer conn.Close()

	if err := sendPacket(conn, cmdAllRead, nil); err != nil {
		return LampState{}, err
	}

	_, _ = recv(conn, 32, time.Second, false)
	data, err := recv(conn, 256, 5*time.Second, true)
	if err != nil {
		return LampState{}, err
	}
	return decodeState(data)
}

func (c Client) PreviewBrightness(ch [Channels]uint8) error {
	conn, err := c.connect()
	if err != nil {
		return err
	}
	defer conn.Close()
	return sendPacket(conn, cmdPreviewLuminance, ch[:])
}

func (c Client) HandLuminance(ch [Channels]uint8) error {
	conn, err := c.connect()
	if err != nil {
		return err
	}
	defer conn.Close()
	if err := sendPacket(conn, cmdHandLuminance, ch[:]); err != nil {
		return err
	}
	drainAck(conn)
	return nil
}

func (c Client) SetModeAuto() error {
	return c.setMode(1)
}

func (c Client) SetModeManual() error {
	return c.setMode(0)
}

func (c Client) SyncTimeLocal() error {
	conn, err := c.connect()
	if err != nil {
		return err
	}
	defer conn.Close()

	now := time.Now()
	data := []byte{byte(now.Hour()), byte(now.Minute()), byte(now.Second())}
	if err := sendPacket(conn, cmdSyncTime, data); err != nil {
		return err
	}
	drainAck(conn)
	return nil
}

func (c Client) PushSchedule(manual [Channels]uint8, schedule [Slots][8]uint8, autoMode bool) error {
	conn, err := c.connect()
	if err != nil {
		return err
	}
	defer conn.Close()

	data := make([]byte, 0, Channels+1+Slots*8+1+3)
	data = append(data, manual[:]...)
	data = append(data, byte(Slots))
	for i := 0; i < Slots; i++ {
		data = append(data, schedule[i][:]...)
	}
	if autoMode {
		data = append(data, 1)
	} else {
		data = append(data, 0)
	}

	now := time.Now()
	data = append(data, byte(now.Hour()), byte(now.Minute()), byte(now.Second()))

	if err := sendPacket(conn, cmdAllSet, data); err != nil {
		return err
	}
	drainAck(conn)
	return nil
}

func (c Client) setMode(mode byte) error {
	conn, err := c.connect()
	if err != nil {
		return err
	}
	defer conn.Close()
	if err := sendPacket(conn, cmdChangeMode, []byte{mode}); err != nil {
		return err
	}
	drainAck(conn)
	return nil
}

func (c Client) connect() (net.Conn, error) {
	addr := fmt.Sprintf("%s:%d", c.Host, c.Port)
	conn, err := net.DialTimeout("tcp", addr, c.Timeout)
	if err != nil {
		return nil, fmt.Errorf("connect %s: %w", addr, err)
	}

	_, _ = recv(conn, 64, 10*time.Millisecond, false)
	return conn, nil
}

func sendPacket(conn net.Conn, cmd [2]byte, data []byte) error {
	packet := make([]byte, 0, 2+2+len(data)+1)
	packet = append(packet, pktStart...)
	packet = append(packet, cmd[0], cmd[1])
	packet = append(packet, data...)
	packet = append(packet, pktEnd)
	_, err := conn.Write(packet)
	return err
}

func recv(conn net.Conn, maxLen int, timeout time.Duration, drain bool) ([]byte, error) {
	deadline := time.Now().Add(timeout)
	if err := conn.SetReadDeadline(deadline); err != nil {
		return nil, err
	}

	out := make([]byte, 0, maxLen)
	buf := make([]byte, maxLen)
	for len(out) < maxLen {
		n, err := conn.Read(buf[:maxLen-len(out)])
		if n > 0 {
			out = append(out, buf[:n]...)
			if !drain {
				return out, nil
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			var netErr net.Error
			if errors.As(err, &netErr) && netErr.Timeout() {
				break
			}
			return out, err
		}
	}
	if len(out) == 0 {
		return out, fmt.Errorf("no response before %s timeout", timeout)
	}
	return out, nil
}

func drainAck(conn net.Conn) {
	_, _ = recv(conn, 32, 150*time.Millisecond, false)
}

func decodeState(data []byte) (LampState, error) {
	if len(data) < 10 {
		return LampState{}, fmt.Errorf("short read-all response: %d bytes", len(data))
	}
	if data[0] != respMagic[0] || data[1] != respMagic[1] {
		return LampState{}, fmt.Errorf("bad response magic: %02x %02x", data[0], data[1])
	}
	if data[len(data)-1] != pktEnd {
		return LampState{}, fmt.Errorf("bad response terminator: %02x", data[len(data)-1])
	}

	var out LampState
	pos := 4
	if pos+Channels+1 > len(data) {
		return LampState{}, fmt.Errorf("response missing manual channels")
	}
	for i := 0; i < Channels; i++ {
		out.Manual[i] = int(data[pos+i])
	}
	pos += Channels

	timeNum := int(data[pos])
	pos++
	if timeNum > Slots {
		return LampState{}, fmt.Errorf("invalid schedule slot count: %d", timeNum)
	}
	if pos+timeNum*8+2 > len(data) {
		return LampState{}, fmt.Errorf("response missing schedule data")
	}
	for i := 0; i < timeNum; i++ {
		for j := 0; j < 8; j++ {
			out.Schedule[i][j] = int(data[pos+j])
		}
		pos += 8
	}

	out.AutoMode = data[pos] != 0
	pos++

	nameEnd := pos
	for nameEnd < len(data)-1 && nameEnd < pos+11 && data[nameEnd] != 0 {
		nameEnd++
	}
	out.Name = string(data[pos:nameEnd])
	out.Valid = true
	return out, nil
}
