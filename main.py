import ccxt
import time
import logging
import os
from dotenv import load_dotenv

# Load environment variables for secure API key handling
load_dotenv()

# Setup logging for monitoring and debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ArbitrageBot:
    def __init__(self, symbols, min_profit=0.005):
        # Initialize exchanges with unified CCXT API
        # Binance uses authenticated credentials; others public for price fetching
        self.exchanges = {
            'okx': ccxt.okx(),  # Public; add keys for full access
            'binance': ccxt.binance({
                'apiKey': os.getenv('BINANCE_API_KEY'),
                'secret': os.getenv('BINANCE_API_SECRET'),
                'enableRateLimit': True,  # Prevents API bans
            }),
            'coinbasepro': ccxt.coinbasepro()  # Public
        }
        # Optional: Enable sandbox for testing with fake funds
        # self.exchanges['binance'].set_sandbox_mode(True)
        
        self.symbols = symbols  # List of trading pairs
        self.min_profit = min_profit  # Minimum net profit threshold
        # EEA-specific fees (taker rates for market orders; customize per tier)
        self.fees = {
            'okx': 0.0035,  # 0.35%
            'binance': 0.001,  # 0.10%
            'coinbasepro': 0.012  # 1.20%
        }
        # Transfer fees (approximate; check exchange for exact)
        self.transfer_fees = {
            'okx': 0.0005,
            'binance': 0.0002,
            'coinbasepro': 0.001
        }

    def fetch_balance(self, exchange, currency='USDT'):
        # Fetches free balance for a currency (e.g., USDT for buys)
        try:
            balance = exchange.fetch_balance()
            available = balance['free'].get(currency, 0)
            logging.info(f"{exchange.id} {currency} balance: {available}")
            return available
        except Exception as e:
            logging.error(f"Error fetching balance from {exchange.id}: {e}")
            return 0

    def fetch_prices(self, symbol):
        # Retrieves bid/ask prices across exchanges
        prices = {}
        for name, ex in self.exchanges.items():
            try:
                ticker = ex.fetch_ticker(symbol)
                prices[name] = {'bid': ticker['bid'], 'ask': ticker['ask']}
                logging.info(f"{name}: {symbol} Bid={prices[name]['bid']}, Ask={prices[name]['ask']}")
            except Exception as e:
                logging.error(f"Error fetching from {name}: {e}")
        return prices

    def detect_spatial_arbitrage(self, prices):
        # Scans for profitable opportunities
        opportunities = []
        for buy_ex in prices:
            for sell_ex in prices:
                if buy_ex == sell_ex:
                    continue
                buy_price = prices[buy_ex]['ask']  # Realistic buy price
                sell_price = prices[sell_ex]['bid']  # Realistic sell price
                if buy_price and sell_price and buy_price > 0:
                    gross_profit = (sell_price - buy_price) / buy_price
                    net_profit = gross_profit - self.fees[buy_ex] - self.fees[sell_ex] - self.transfer_fees[buy_ex] - 0.001  # Buffer for slippage
                    if net_profit > self.min_profit:
                        opportunities.append({
                            'buy_exchange': buy_ex,
                            'sell_exchange': sell_ex,
                            'buy_price': buy_price,
                            'sell_price': sell_price,
                            'profit': net_profit * 100  # As percentage
                        })
        return opportunities

    def execute_trade(self, exchange, side, symbol, amount):
        # Places market order
        try:
            if side == 'buy':
                order = exchange.create_market_buy_order(symbol, amount)
            else:
                order = exchange.create_market_sell_order(symbol, amount)
            logging.info(f"Executed {side} on {exchange.id}: {order}")
            return order
        except Exception as e:
            logging.error(f"Trade error on {exchange.id}: {e}")
            return None

    def run(self):
        # Main loop: Poll, detect, execute
        while True:
            for symbol in self.symbols:
                prices = self.fetch_prices(symbol)
                opps = self.detect_spatial_arbitrage(prices)
                if opps:
                    logging.info(f"Arbitrage Opportunity Found for {symbol}: {opps}")
                    for opp in opps:
                        # Execute only if Binance involved (authenticated)
                        if opp['buy_exchange'] == 'binance' or opp['sell_exchange'] == 'binance':
                            base = symbol.split('/')[0]  # e.g., BTC
                            quote = symbol.split('/')[1]  # e.g., USDT
                            if opp['buy_exchange'] == 'binance':
                                balance = self.fetch_balance(self.exchanges['binance'], quote)
                                amount = min(100 / prices['binance']['ask'], balance / prices['binance']['ask'])  # $100 cap
                            else:
                                balance = self.fetch_balance(self.exchanges['binance'], base)
                                amount = min(0.001, balance)  # Small amount
                            if amount <= 0:
                                logging.warning(f"Insufficient funds on Binance for {symbol}")
                                continue
                            # Execute
                            if opp['buy_exchange'] == 'binance':
                                buy_order = self.execute_trade(self.exchanges['binance'], 'buy', symbol, amount)
                                if buy_order:
                                    logging.info("Manual transfer required to sell")
                            elif opp['sell_exchange'] == 'binance':
                                sell_order = self.execute_trade(self.exchanges['binance'], 'sell', symbol, amount)
                                if sell_order:
                                    logging.info("Ensure funds on Binance for sell")
            time.sleep(5)  # Adjustable interval

# Usage Example
symbols = ['BTC/USDT', 'ETH/USDT']
bot = ArbitrageBot(symbols)
bot.run()