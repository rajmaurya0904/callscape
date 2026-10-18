package main

import "example.com/goapp/util"

type Base struct{}

func (b *Base) Ping() {}

type Server struct {
	Base
	Cfg util.Config
}

func (s *Server) Run() {
	s.Ping()
	s.handle()
	util.Log("x")
}

func (s *Server) handle() { helper() }

func helper() {}

func main() {
	s := &Server{}
	s.Run()
}
