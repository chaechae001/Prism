"""Conservative headline topic overrides for broad economy RSS inputs.

This is a display rule, not a trained classifier. Original batch labels stay intact.
"""
import re

VERSION='headline-topics-v1'
FINANCE=re.compile(r'코스피|코스닥|주가|증시|시가총액|상장|IPO|국채|기준금리|환율|금융|부동산|주택|관세|물가',re.I)
POLITICS=re.compile(r'대통령|국회|총선|대선|탄핵|국정감사|정당|여당|야당|외교부')
SOCIETY=re.compile(r'산업재해|산재|유족|노동계|노동부|형사\s*처벌|교통사고|살인|실종|교육청|입시|학교폭력|환불|피해\s*속출')
TECHNOLOGY=re.compile(r'PHP|해킹|사이버|취약점|서버\s*장악|취약\s*서버|랜섬웨어|정보통신|인공지능|생성형\s*AI|반도체\s*기술',re.I)


def display_category(original,title):
    if original!='economy': return original
    if FINANCE.search(title): return original
    if POLITICS.search(title): return 'politics'
    if SOCIETY.search(title): return 'society'
    if TECHNOLOGY.search(title): return 'technology'
    return original
