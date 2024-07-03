# Restic Password Generator

This Python script generates secure passwords suitable for use with Restic backups. It allows you to generate one or multiple passwords and optionally save them to a file.

## Features

- Generate cryptographically strong passwords
- Specify the number of passwords to generate
- Option to save passwords to a file or print to console
- Customizable through command-line arguments

## Requirements

- Python 3.6 or higher

## Installation

1. Clone this repository or download the `restic_password_generator.py` file.
2. Ensure you have Python 3.6 or higher installed on your system.

## Usage

Run the script from the command line using Python. Here are some example commands:

1. Generate one password and print it to the console:

   ```
   python restic_password_generator.py
   ```

2. Generate multiple passwords:

   ```
   python restic_password_generator.py -n 5
   ```

3. Generate passwords and save them to a file:

   ```
   python restic_password_generator.py -n 3 -o passwords.txt
   ```

### Command-line Arguments

- `-n`, `--num-passwords`: Number of passwords to generate (default: 1)
- `-o`, `--output`: Output file name (optional)

## Security Note

This script uses Python's `secrets` module to generate cryptographically strong random passwords. The generated passwords include a mix of ASCII letters (both uppercase and lowercase), digits, and punctuation characters.

## Contributing

Feel free to fork this repository and submit pull requests with any enhancements.

## License

This project is open source and available under the [MIT License](https://opensource.org/licenses/MIT).
