package util

type Config struct{ Name string }

func Log(m string) { format(m) }
func format(m string) string { return m }
