import argparse
import secrets
import string
import sys

def generate_password(length=32):
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def main():
    parser = argparse.ArgumentParser(description="Generate secure restic backup passwords")
    parser.add_argument("-n", "--num-passwords", type=int, default=1, help="Number of passwords to generate")
    parser.add_argument("-o", "--output", type=str, help="Output file name")
    args = parser.parse_args()

    passwords = [generate_password() for _ in range(args.num_passwords)]

    if args.output:
        with open(args.output, 'w') as f:
            for password in passwords:
                f.write(f"{password}\n")
        print(f"Passwords written to {args.output}")
    else:
        for password in passwords:
            print(password)

if __name__ == "__main__":
    main()