package main

import (
	"flag"
	"log"
	"net/http"
	"os/exec"
	"runtime"
	"strings"
	"time"

	"github.com/bitbarista/k7-led-controller/pc-bridge/internal/bridge"
)

func main() {
	listen := flag.String("listen", "127.0.0.1:8787", "HTTP listen address")
	configPath := flag.String("config", "k7-pc-bridge.json", "bridge store path")
	timeout := flag.Duration("timeout", 500*time.Millisecond, "lamp TCP command timeout")
	noOpen := flag.Bool("no-open", false, "do not open the local UI in the default browser")
	flag.Parse()

	srv, err := bridge.NewServer(*configPath, *timeout)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	uiURL := browserURL(*listen)
	log.Printf("K7 PC bridge listening on %s", uiURL)
	log.Printf("Lamp target is %s:%d", srv.Config().Host, srv.Config().Port)
	if !*noOpen {
		go func() {
			time.Sleep(250 * time.Millisecond)
			if err := openBrowser(uiURL); err != nil {
				log.Printf("Open browser failed: %v", err)
				log.Printf("Open %s manually", uiURL)
			}
		}()
	}
	if err := http.ListenAndServe(*listen, srv.Routes()); err != nil {
		log.Fatal(err)
	}
}

func browserURL(listen string) string {
	host := listen
	if idx := strings.LastIndex(host, ":"); idx > -1 {
		host = host[:idx]
	}
	if host == "" || host == "0.0.0.0" || host == "::" || host == "[::]" {
		listen = "127.0.0.1" + listen[strings.LastIndex(listen, ":"):]
	}
	return "http://" + listen + "/"
}

func openBrowser(url string) error {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	case "darwin":
		cmd = exec.Command("open", url)
	default:
		cmd = exec.Command("xdg-open", url)
	}
	return cmd.Start()
}
