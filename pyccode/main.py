"""CLI entry point: dispatches single-prompt or interactive REPL mode."""
import sys

from pyccode.chat import chat


def main():
    """Entry point for the pyccode CLI."""
    if len(sys.argv) > 1:
        print(chat(sys.argv[1]))
    else:
        # interactive
        history = []
        while True:
            try:
                prompt = input("\033[36m>> \033[0m")
            except KeyboardInterrupt:
                print("\nExiting...")
                break

            if prompt in ('q', 'quit', "exit"):
                print("\nExiting...")
                break

            print(chat(prompt, history))
