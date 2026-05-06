package main

import (
	"flag"
	"log"
	"net/http"
	"time"

	"github.com/bitbarista/k7-led-controller/pc-bridge/internal/bridge"
)

func main() {
	listen := flag.String("listen", "127.0.0.1:8787", "HTTP listen address")
	configPath := flag.String("config", "k7-pc-bridge.json", "bridge store path")
	timeout := flag.Duration("timeout", 500*time.Millisecond, "lamp TCP command timeout")
	flag.Parse()

	srv, err := bridge.NewServer(*configPath, *timeout)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	log.Printf("K7 PC bridge listening on http://%s", *listen)
	log.Printf("Lamp target is %s:%d", srv.Config().Host, srv.Config().Port)
	if err := http.ListenAndServe(*listen, srv.Routes()); err != nil {
		log.Fatal(err)
	}
}
