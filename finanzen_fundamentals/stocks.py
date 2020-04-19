#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re

import numpy as np
import pandas as pd
import requests
from lxml import html

# Import Modules
from finanzen_fundamentals.scraper import _make_soup
from . import statics


def parse_for_isin(string_object: str):
    """get ISIN from string. Return None if pattern not found."""
    isin = None
    isin_pattern = r"[a-zA-Z]{2}[A-Z0-9]{9}\d"
    # ISIN ISO 6166
    isin_re = re.search(isin_pattern, string_object)
    if isin_re:
        isin = isin_re.group()

    return isin


def join_url(url: str, search_value: str):
    """if search value is an ISIN use different url."""
    isin = parse_for_isin(search_value)
    url = url + search_value
    if isin is not None:
        url = r"https://www.finanzen.net/suchergebnis.asp?_search=" + search_value

    return url, isin


def get_isin_from_soup(soup):
    isin = None
    isin_soup = soup.find("meta", property="og:title")
    if isin_soup:
        isin = parse_for_isin(isin_soup["content"])

    return isin

# Define Function to Check for Error
def _check_site(soup):
    message = soup.find("div", {"class": "special_info_box"})
    if message is not None:
        message_text = message.get_text()
        load_error = "Die gewünschte Seite konnte nicht angezeigt werden"
        if load_error in message_text:
            raise ValueError("Could not find Stock")


def get_indices(url: str="https://www.finanzen.net/index/dax/30-werte"):
    """use base url and parse url of other indices"""
    soup = _make_soup(url)
    table = soup.find("ul", attrs={"class": "box-nav"})
    # bs4 ResultSet containing all <li>-tags.
    index_links = table.find_all("li")

    indices = dict()
    for result in index_links:
        indices[result.a.text] = "{}{}".format("https://www.finanzen.net", result.a["href"])

    return indices


def get_stocks_in_index(url: str):
    """"""
    soup = _make_soup(url)
    table = soup.find("div", attrs={"class": "box", "id": "index-list-container"})
    stocks_in_index = pd.read_html(table.prettify())
    assert len(stocks_in_index) == 1

    stocks_in_index = extract_stock_from_df(stocks_in_index[0])
    
    return stocks_in_index


def extract_stock_from_df(index_df: pd.DataFrame):
    """return dictionary {stock_i: ISIN_i, ...}"""
    # set stock as index and ISIN as column value
    res = index_df.iloc[:, 0].str.split("  ", expand=True).set_index(0)
    # transpose data frame and convert result to dictionary where key=stock name, value=ISIN
    res = res.T.to_dict("records")

    assert len(res) == 1

    return res[0]
    

# Define Function to Extract GuV/Bilanz from finanzen.net
def get_fundamentals(stock: str):
    # Convert name to lowercase
    stock = stock.lower()
    url, isin = join_url("https://www.finanzen.net/bilanz_guv/", stock)
    # Load Data
    soup = _make_soup(url)

    # Check for Error
    _check_site(soup)

    # Define Function to Parse Table
    def _parse_table(soup, signaler: str):
        table_dict = {}
        table = soup.find("h2", text=re.compile(signaler)).parent
        years = [x.get_text() for x in table.find_all("th")[2:]]
        rows = table.find_all("tr")[1:]
        for row in rows:
            name = row.find("td", {"class": "font-bold"}).get_text()
            row_data = row.find_all("td")
            row_data = row_data[2:]
            row_data = [x.get_text() for x in row_data]
            row_data = [re.sub(r"\.", "", x) for x in row_data]
            row_data = [re.sub(",", ".", x) for x in row_data]
            row_data = [float(x) if x != "-" else None for x in row_data]
            table_dict[name] = dict(zip(years, row_data))
        return table_dict

    # Extract Stock Quote Info+
    try:
        quote_info = _parse_table(soup, "Die Aktie")
    except Exception:
        quote_info = None

    # Extract Key Ratios
    try:
        key_ratios = _parse_table(soup, "Unternehmenskennzahlen")
    except Exception:
        key_ratios = None

    # Extract Income Statement
    try:
        income_info = _parse_table(soup, "GuV")
    except Exception:
        income_info = None

    # Extract Balance Sheet
    try:
        balance_sheet = _parse_table(soup, "Bilanz")
    except Exception:
        balance_sheet = None

    isin = isin if isin else get_isin_from_soup(soup)

    # Extract Other Information
    try:
        other_info = _parse_table(soup, "sonstige Angaben")
    except Exception:
        other_info = None

    # Collect Fundamentals into single Directory
    fundamentals = {
        "Quotes": quote_info,
        "Key Ratios": key_ratios,
        "Income Statement": income_info,
        "Balance Sheet": balance_sheet,
        "ISIN": isin.upper(),
        "Other": other_info
    }

    # Return Fundamentals
    return fundamentals


def get_chart_infos(stock: str):
    # Convert name to lowercase
    stock = stock.lower()
    url, isin = join_url("https://www.finanzen.net/aktien/", stock)

    # Load Data
    soup = _make_soup(url)
    # Check for Error
    _check_site(soup)

    # Define Function to Parse Table
    def _parse_table(soup, signaler: str):
        table = soup.find("h3", text=re.compile(signaler), attrs={"class": "box-headline"}).parent
        # returns a list of data frames. Choose first one (asserting only one exists anyway)
        df_table = pd.read_html(table.prettify(), decimal=",", thousands=".")[0]
        # set first column as index
        df_table.set_index(keys=df_table.columns.values[0], inplace=True)
        return df_table

    try:
        performance_info = _parse_table(soup, "Performance")
    except Exception as msg:
        print(f"Warning {msg}. Setting performance_info=None.")
        performance_info = None

    isin = isin if isin else get_isin_from_soup(soup)

    chart_infos = {
        'ISIN': isin.upper(),
        'Performance': performance_info.to_dict("index"),
    }

    return chart_infos


# Define Function to Extract Estimates
def get_estimates(stock: str):
    # Convert Stock Name to Lowercase
    stock = stock.lower()

    # Load Data
    soup = _make_soup("https://www.finanzen.net/schaetzungen/" + stock)

    # Check for Error
    _check_site(soup)

    # Parse Table containing Yearly Estimates
    table_dict = {}
    table = soup.find("h1", text=re.compile("^Schätzungen")).parent
    years = table.find_all("th")[1:]
    years = [x.get_text() for x in years]
    rows = table.find_all("tr")[1:]
    for row in rows:
        fields = row.find_all("td")
        fields = [x.get_text() for x in fields]
        name = fields[0]
        row_data = fields[1:]
        row_data = [x if x != "-" else None for x in row_data]
        row_data = [re.sub("[^\d,]", "", x) if x is not None else x for x in row_data]
        row_data = [re.sub(",", ".", x) if x is not None else x for x in row_data]
        row_data = [float(x) if x is not None else x for x in row_data]
        table_dict[name] = dict(zip(years, row_data))

    # Return Estimates in Dict
    return table_dict


# Define Function to Search for Stocks
def search_stock(stock: str, limit: int = -1):
    # Convert Stock Name to Lowercase
    stock = stock.lower()

    # Make Request
    soup = _make_soup("https://www.finanzen.net/suchergebnis.asp?_search=" + stock)

    # Check for Error
    if soup.find("div", {"class": "red"}) is not None:
        if "kein Ergebnis geliefert" in soup.find("div", {"class": "red"}).get_text():
            return list()

    # Define Function to Extract Results
    result_list = []
    table = soup.find("table", {"class": "table"})
    rows = table.find_all("tr")
    for row in rows[1:]:
        cells = row.find_all("td")
        name = cells[0].get_text()
        link = cells[0].find("a")["href"]
        link = "https://www.finanzen.net" + link
        result_list.append((name, link))

    # Filter Result if limit was given
    if limit > 0:
        # Decrease limit if bigger than result
        result_len = len(result_list)
        if limit > result_len:
            limit = result_len
        result_list = result_list[0:limit]

    # Return Result List as formatted String
    for result in result_list:
        result_name = result[0]
        result_short = re.search("aktien/(.+)-aktie", result[1]).group(1)
        print("{}: {}".format(result_name, result_short))


### backster82 additional functions

def check_site_availability(url):
    try:
        r = requests.get(url)
    except requests.exceptions.RequestException as e:
        raise SystemExit(e)


def get_parser(function, stock_name):
    base_url = "https://www.finanzen.net"

    functions = {
        "search": "/suchergebnis.asp?_search=",
        "stock": "/aktien/",
        "estimates": "/schaetzungen/",
        "fundamentals": "/bilanz_guv/",
        "index": "/index/"
    }

    if function not in functions:
        raise ValueError("Got unknown function %r in get_parser" % function)
        return 1

    check_site_availability(base_url)

    url = base_url + functions[function] + stock_name
    response = requests.get(url, verify=True)

    parser = html.fromstring(response.text)

    return parser


def get_estimates_lxml(stock: str, results=[]):
    url = "https://www.finanzen.net/schaetzungen/" + stock

    xp_base_xpath = '//div[contains(@class, "box table-quotes")]//h1[contains(text(), "Schätzungen")]//..'
    xp_data = xp_base_xpath + '//table//tr'

    response = requests.get(url, verify=True)
    parser = html.fromstring(response.text)

    data_table = []

    header_row = 0

    for data_element in parser.xpath(xp_data):
        table_row = []
        for i in data_element:
            table_row.append(i.xpath('./text()')[0])

        if header_row != 0:
            for i in range(1, len(table_row)):
                if not table_row[i] == '-':
                    table_row[i] = table_row[i].replace(".", "").replace(",", ".")
                    table_row[i] = float(table_row[i].split(" ")[0])

        else:
            table_row[0] = "Estimation"
            header_row = 1

        data_table.append(table_row)
        dataframe = pd.DataFrame(list(map(np.ravel, data_table)))
        dataframe.columns = dataframe.iloc[0]
        dataframe.drop(dataframe.index[0], inplace=True)

    return dataframe


def get_fundamentals_lxml(stock: str, results=[]):
    url = "https://www.finanzen.net/bilanz_guv/" + stock

    tables = ["Die Aktie",
              "Unternehmenskennzahlen",
              "GuV",
              "Bilanz",
              "sonstige Angaben"
              ]

    complete_data_set = []

    for table in tables:
        parser = get_parser("fundamentals", stock)

        xp_base = '//div[contains(@class, "box table-quotes")]//h2[contains(text(), "' + table + '")]//..'
        xp_head = xp_base + '//table//thead//tr'
        xp_data = xp_base + '//table//tbody'

        parsed_data_table = parser.xpath(xp_base)

        # drop second empty element in parsed_data_table
        # ToDo: find out why parser.xpath(xp_base) returns 2 elements
        # parsed_data_table.pop()

        for data_element in parsed_data_table:
            header_array = []
            table_data = []
            for i in data_element.xpath('.//table//thead//tr//th/text()'):
                header_array.append(i)

            table_data.append(header_array)

            # first table element is an checkbox so we'll drop it
            first_col = True
            for i in data_element.xpath('.//table//tr'):
                if not first_col:
                    data = i.xpath('.//td/text()')
                    for cnt in range(1, len(data)):
                        data[cnt] = data[cnt].replace(".", "").replace(",", ".")
                    table_data.append(data)
                else:
                    first_col = False

            dataframe = pd.DataFrame(list(map(np.ravel, table_data)))
            dataframe.columns = dataframe.iloc[0]
            dataframe.drop(dataframe.index[0], inplace=True)

            complete_data_set.append(dataframe)

    return pd.concat(complete_data_set, ignore_index=True)


def get_current_value_lxml(stock: str, exchange="TGT", results=[]):
    data_columns = [
        "name",
        "wkn",
        "isin",
        "symbol",
        "price",
        "currency",
        "chg_to_open",
        "chg_percent",
        "time",
        "exchange"
    ]

    url = "https://www.finanzen.net/aktien/" + stock + "-aktie" + statics.StockMarkets[exchange][
        'url_postfix']
    response = requests.get(url, verify=True)

    # sleep()
    parser = html.fromstring(response.text)
    summary_table = parser.xpath('//div[contains(@class,"row quotebox")][1]')

    i = 0

    summary_data = []

    for table_data in summary_table:
        raw_price = table_data.xpath(
            '//div[contains(@class,"row quotebox")][1]/div[contains(@class, "col-xs-5")]/text()')
        raw_currency = table_data.xpath(
            '//div[contains(@class,"row quotebox")][1]/div[contains(@class, "col-xs-5")]/span//text()')
        raw_change = table_data.xpath(
            '//div[contains(@class,"row quotebox")][1]/div[contains(@class, "col-xs-4")]/text()')
        raw_percentage = table_data.xpath(
            '//div[contains(@class,"row quotebox")][1]/div[contains(@class, "col-xs-3")]/text()')
        raw_name = table_data.xpath('//div[contains(@class, "col-sm-5")]//h1/text()')
        raw_instrument_id = table_data.xpath('//span[contains(@class, "instrument-id")]/text()')
        raw_time = table_data.xpath('//div[contains(@class,"row quotebox")]/div[4]/div[1]/text()')
        raw_exchange = table_data.xpath('//div[contains(@class,"row quotebox")]/div[4]/div[2]/text()')

        name = ''.join(raw_name).strip()
        time = ''.join(raw_time).strip()
        exchange = ''.join(raw_exchange).strip()

        instrument_id = ''.join(raw_instrument_id).strip()
        (wkn, isin) = instrument_id.split(sep='/')
        if 'Symbol' in isin:
            (isin, sym) = isin.split(sep='Symbol')
        else:
            sym = ""

        currency = ''.join(raw_currency).strip()

        summary_data = [
            name.replace('&nbsp', ''),
            wkn.replace(' ', '').replace("WKN:", ""),
            isin.replace(' ', '').replace("ISIN:", ""),
            sym.replace(' ', '').replace(":", ""),
            float(raw_price[0].replace(',', '.')),
            currency,
            float(raw_change[0].replace(',', '.')),
            float(raw_percentage[0].replace(',', '.')),
            time,
            statics.StockMarkets[exchange]['real_name']
        ]

    return pd.DataFrame(data=[summary_data], columns=data_columns)


def search_stock_lxml(stock: str, limit: int = -1, results=[]):
    indices = ["name", "fn_stock_name", "isin", "wkn"]
    df = pd.DataFrame(columns=indices)

    parser = get_parser("search", stock)

    table_xpath = '//div[contains(@class, "table")]//tr'
    summary_table = parser.xpath(table_xpath)

    if len(summary_table) == 0:
        raise ValueError("Site did find any entries for %r" % stock)

    skip_first_element = 0
    results = []

    for table_element in summary_table:
        # Todo: Find cause for the first element being [] []
        if skip_first_element == 0:
            skip_first_element = 1
        else:
            raw_name = ''.join(table_element.xpath('.//a/text()')).strip()
            raw_link = ''.join(table_element.xpath('.//a//@href')).strip()
            raw_isin = ''.join(table_element.xpath('.//td')[1].xpath('./text()')).strip()
            raw_wkn = ''.join(table_element.xpath('.//td')[2].xpath('./text()')).strip()

            fn_stock_name = raw_link.replace("/aktien/", "").replace("-aktie", "")

            if limit == 0:
                break
            elif limit > 0:
                limit = limit - 1
                df = df.append(pd.DataFrame(data=[[raw_name, fn_stock_name, raw_isin, raw_wkn]], columns=indices))
            else:
                df = df.append(pd.DataFrame(data=[[raw_name, fn_stock_name, raw_isin, raw_wkn]], columns=indices))

    return df
