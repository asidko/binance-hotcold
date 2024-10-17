# 🔥 HotCold ❄️

Binance Futures symbol lookup tool

[👉 Ukrainian version](README_uk.md)

## Usage examples

### Simple mode

Use this mode to quickly check what symbols got an unexpected boost 🐳.

🎩Example. Give TOP symbols that changed the most in the last **40 minutes**

```bash
python hotcold.py 40m
```

<img width="685" alt="Simple mode example" src="https://github.com/user-attachments/assets/de2e4f28-97a5-46ae-a887-f6ec6bd65f19">

### Research mode

Use this mode to see what's going on in the market 📈 and find interesting symbols to trade.

🎩 Example. Give TOP symbols, compare the price on last **20 minutes** with the price on last **8 hours** and last **3 days**

```bash
python hotcold.py 20m 4h 3d
```

<img width="730" alt="image" src="https://github.com/user-attachments/assets/916a9d43-5c0e-4784-94ad-462b63d7af3a">

## Installation

1. Make sure python is installed on your machine

Example of installation on Ubuntu Linux:
```bash
sudo apt-get update -y && sudo apt-get install -y python3 python3-pip python-is-python3
```

Example of installation on Android (Termux):
```bash
pkg update && pkg upgrade -y && pkg install -y python
```

2. Download the script to your machine<br>

```bash
# Download the script form the repository
curl -O https://raw.githubusercontent.com/asidko/binance-hotcold/main/hotcold.py
# ☝️ Repeat this command later if you want to update the script to a newer version
```

3. Install required python packages

```bash
pip install aiohttp rich
```

4. Run the script (check the usage examples above)

```bash
python hotcold.py 15m 4h 1d
```

## Special params

### --help

Example: `python hotcold.py --help`

See all available options

### --watch

Example: `python hotcold.py 3m 1h 8h --watch`

Automatically request new data every 30 seconds and show it

You can change the interval by passing `--interval=300` (in seconds) to request data every 5 minutes

### --count

Example: `python hotcold.py 15m 1d 5d --count=12`

Increases the number of symbols to show (for both categories). Default is to show 5 boosted and 5 dropped symbols

### --no-spikes

Example: `python hotcold.py 15m 1d 5d --no-spikes`

Ignores symbols with unexpected spikes of price.

⚠️ Significantly affects the search results. Use only if necessary.

Use it if you don't want to see symbols like this

<img width="691" alt="image" src="https://github.com/user-attachments/assets/6aa9855d-7504-4d86-8c51-546db304d5f5">

And rather interested in more evenly distributed charts like this

<img width="671" alt="image" src="https://github.com/user-attachments/assets/56eb84ce-274e-4c24-9ea6-d56415656023">

Additionally, you can specify a threshold to filter the unstable coins. 
For example, to ignore all symbols with a price spike of more than 3% in the last 2 days , use the following command:

```bash
# Find the most stable symbols
python hotcold.py 15m 2h 2d --no-spikes --spike-threshold=3%
``` 

<img width="720" alt="image" src="https://github.com/user-attachments/assets/f08b2d5f-ba30-4613-be1f-5e8c847597de">

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details