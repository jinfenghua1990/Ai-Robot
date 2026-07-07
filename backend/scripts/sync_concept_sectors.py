"""
同步概念板块及成分股到 concept_sectors 表
多源优先级：新浪财经 > AkShare(东财) > 同花顺(THS) > 内置兜底
- 新浪财经：可拿全量概念板块列表 + 成分股（node=gn_xxx）
- AkShare：stock_board_concept_name_em + stock_board_concept_cons_em
- Tushare：ths_index + ths_member（需积分权限）
"""
import os
import sys
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# 将 backend 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.connection import get_db, engine, Base
from db.session import get_db_session
from db.models import ConceptSector
from sqlalchemy import func
import logging
from utils.http_constants import SINA_HEADERS, clear_proxy_env
logger = logging.getLogger(__name__)

clear_proxy_env()

# 内置兜底：热门概念板块及代表性成分股 ts_code
# 每条 key 上方的注释为该概念的中文释义，便于阅读维护
FALLBACK_CONCEPTS = {
    # GLP-1 等减肥药物研发/生产，诺和诺德司美格鲁酯、礼来替尔泊肽引爆的全球减肥药热潮
    '减肥药': [
        '000766.SZ', '002317.SZ', '002551.SZ', '002675.SZ', '002898.SZ',
        '300006.SZ', '300199.SZ', '300255.SZ', '300381.SZ', '300452.SZ',
        '600276.SH', '600380.SH', '600436.SH', '600664.SH', '603590.SH',
    ],
    # DRAM/NAND/利基存储等半导体存储器，涵盖内存、闪存、EEPROM、SRAM 等芯片设计/制造
    '存储芯片': [
        '000021.SZ', '002049.SZ', '002077.SZ', '300223.SZ', '300613.SZ',
        '300672.SZ', '300782.SZ', '600667.SH', '603005.SH', '603986.SH',
        '688008.SH', '688018.SH', '688110.SH', '688525.SH', '688981.SH',
    ],
    # Printed Circuit Board 印刷电路板，电子元器件的载体与电气互连基板，AI 服务器/消费电子上游
    'PCB概念': [
        '002463.SZ', '002436.SZ', '002579.SZ', '002913.SZ', '002938.SZ',
        '300476.SZ', '300739.SZ', '600183.SH', '600601.SH', '603228.SH',
        '603920.SH', '605058.SH', '688183.SH', '688655.SH', '300814.SZ',
    ],
    # AI 大模型、深度学习、AIGC、智能算法等相关技术与应用场景
    '人工智能': [
        '000063.SZ', '002230.SZ', '002362.SZ', '002405.SZ', '300002.SZ',
        '300033.SZ', '300418.SZ', '300496.SZ', '600728.SH', '600756.SH',
        '603019.SH', '603496.SH', '688256.SH', '688561.SH', '688787.SH',
    ],
    # Co-Packaged Optics 光电共封装：把光模块与交换芯片共封装，降低功耗，AI 数据中心 800G/1.6T 高速互联核心方向
    '共封装光学CPO': [
        '002281.SZ', '002902.SZ', '300308.SZ', '300394.SZ', '300502.SZ',
        '300570.SZ', '300620.SZ', '300638.SZ', '600498.SH', '603083.SH',
        '603220.SH', '605117.SH', '688205.SH', '688498.SH', '688717.SH',
    ],
    # 工业机器人、服务机器人、特种机器人本体及核心零部件（减速器、伺服、控制器）
    '机器人概念': [
        '002031.SZ', '002050.SZ', '002124.SZ', '002472.SZ', '002527.SZ',
        '002559.SZ', '002747.SZ', '300024.SZ', '300607.SZ', '300124.SZ',
        '600580.SH', '603666.SH', '688017.SH', '688165.SH', '688320.SH',
    ],
    # 3000 米以下低空空域的无人机/eVTOL/通用航空产业，物流、文旅、城市空中交通新业态
    '低空经济': [
        '000099.SZ', '002023.SZ', '002151.SZ', '002413.SZ', '002929.SZ',
        '300011.SZ', '300114.SZ', '300411.SZ', '300900.SZ', '600038.SH',
        '600316.SH', '600372.SH', '600843.SH', '688002.SH', '688070.SH',
    ],
    # 使用固态电解质替代液态电解液的锂电池，高能量密度+高安全性，下一代动力电池技术
    '固态电池': [
        '000009.SZ', '002074.SZ', '002091.SZ', '002240.SZ', '002709.SZ',
        '002812.SZ', '300014.SZ', '300073.SZ', '300037.SZ', '300568.SZ',
        '600110.SH', '600884.SH', '603659.SH', '688005.SH', '688778.SH',
    ],
    # 黄金采选、冶炼、销售及黄金珠宝品牌，避险资产+通胀保值属性
    '黄金概念': [
        '000506.SZ', '000975.SZ', '002155.SZ', '002237.SZ', '002716.SZ',
        '600489.SH', '600547.SH', '600612.SH', '600766.SH', '600988.SH',
        '601069.SH', '601127.SH', '601899.SH', '603979.SH', '688503.SH',
    ],
    # 数据中心 224G/448G 高速铜缆（DAC/AEC/ACC），替代光模块的低成本短距互联方案，AI 算力配套
    '铜缆高速连接': [
        '000938.SZ', '002130.SZ', '002475.SZ', '002897.SZ', '300120.SZ',
        '300351.SZ', '300563.SZ', '300843.SZ', '600110.SH', '600522.SH',
        '600973.SH', '603042.SH', '605277.SH', '688668.SH', '688800.SH',
    ],
    # 智能网联汽车"车端-路侧-云端"协同的 V2X 智能交通体系，自动驾驶基础设施
    '车路云': [
        '000063.SZ', '002151.SZ', '002236.SZ', '002373.SZ', '002906.SZ',
        '300212.SZ', '300552.SZ', '600728.SH', '600845.SH', '601186.SH',
        '603023.SH', '603496.SH', '688088.SH', '688111.SH', '688208.SH',
    ],
    # 民营企业主导的航天发射、卫星制造、星座运营等太空产业，对标 SpaceX、Starlink
    '商业航天': [
        '000901.SZ', '002025.SZ', '002179.SZ', '002405.SZ', '300034.SZ',
        '300053.SZ', '300101.SZ', '300455.SZ', '600118.SH', '600316.SH',
        '600343.SH', '600501.SH', '600760.SH', '688523.SH', '688631.SH',
    ],
    # AI 服务器、GPU、数据中心等提供的计算能力，大模型训练/推理的上游基础设施
    '算力': [
        '603019.SH', '000977.SZ', '688041.SH', '603496.SH', '000938.SZ',
        '002261.SZ', '600756.SH', '300212.SZ', '300474.SZ', '600498.SH',
        '300502.SZ', '300308.SZ', '300394.SZ', '002837.SZ', '300545.SZ',
    ],
    # 用液体（水/氟化液）替代风冷给高功率 AI 芯片散热的技术，冷板式/浸没式/喷淋式路线
    '液冷': [
        '000977.SZ', '603019.SH', '300499.SZ', '002837.SZ', '301018.SZ',
        '301149.SZ', '603912.SH', '300249.SZ', '300017.SZ', '300442.SZ',
        '300738.SZ', '002212.SZ', '603887.SH', '300383.SZ', '300469.SZ',
    ],
    # 可控核聚变（人造太阳），磁约束/惯性约束路线，终极清洁能源，磁体/真空室/包层关键部件
    '核聚变': [
        '601611.SH', '000881.SZ', '002318.SZ', '600875.SH', '601727.SH',
        '600848.SH', '000969.SZ', '688122.SH', '603011.SH', '300629.SZ',
        '002255.SZ', '002046.SZ', '600482.SH', '688190.SH', '603698.SH',
    ],
    # 人工智能在各行业的落地应用：办公、教育、营销、法律、医疗、Agent 等垂直场景
    'AI应用': [
        '002230.SZ', '688111.SH', '300624.SZ', '300418.SZ', '300364.SZ',
        '603533.SH', '300959.SZ', '300058.SZ', '300031.SZ', '300654.SZ',
        '300781.SZ', '300792.SZ', '600556.SH', '300770.SZ', '300612.SZ',
    ],
    # 仿人形双足机器人，特斯拉 Optimus、宇树、智元等代表产品，AI+精密机械融合载体
    '人形机器人': [
        '688017.SH', '002472.SZ', '601689.SH', '002050.SZ', '002747.SZ',
        '300124.SZ', '603728.SH', '688160.SH', '002896.SZ', '300607.SZ',
        '603595.SH', '002931.SZ', '688698.SH', '300660.SZ', '688022.SH',
    ],
    # 半导体芯片设计、制造、封测、设备、材料全产业链，集成电路国产替代核心
    '半导体': [
        '688981.SH', '002049.SZ', '603501.SH', '688012.SH', '603986.SH',
        '300142.SZ', '300661.SZ', '300223.SZ', '300613.SZ', '300672.SZ',
        '300782.SZ', '300327.SZ', '002049.SZ', '002156.SZ', '002449.SZ',
        '300054.SZ', '300077.SZ', '300131.SZ', '300223.SZ', '300257.SZ',
        '600584.SH', '600667.SH', '600745.SH', '603005.SH', '603160.SH',
        '603290.SH', '603986.SH', '688012.SH', '688085.SH', '688107.SH',
        '688110.SH', '688126.SH', '688185.SH', '688200.SH', '688256.SH',
        '688261.SH', '688272.SH', '688361.SH', '688385.SH', '688396.SH',
        '688422.SH', '688432.SH', '688521.SH', '688525.SH', '688561.SH',
        '688630.SH', '688702.SH', '688720.SH', '688726.SH', '688728.SH',
    ],
}

# 外部数据源（新浪/AkShare/Tushare）同步的概念板块中文释义索引
# 按 A 股市场术语 / 地理政策 / 公司品牌 / 专业缩写 / 医药生物 / 新能源材料 /
#    半导体电子科技 / 消费农业 / 环保节能 / 金融改革 / 军工航天 等类别分组
# 与 FALLBACK_CONCEPTS 中的 19 个概念互补，合计覆盖当前数据库中全部 188 个概念板块
CONCEPT_DESCRIPTIONS = {
    # ========== A 股市场术语 / 投资黑话 ==========
    'ST板块': 'Special Treatment，对财务异常公司股票特别处理，日涨跌幅限制 5%',
    '准ST股': '濒临被 ST 的股票，存在被特别处理风险',
    '超大盘': '市值超大的蓝筹股，对指数影响显著',
    '摘帽概念': 'ST 公司撤销特别处理，恢复正常交易状态',
    '送转潜力': '可能高比例送红股或转增股本，引发股价炒作',
    '未股改': '尚未完成股权分置改革的历史遗留股票',
    '本月解禁': '本月有限售股解禁可上市流通，可能带来抛压',
    '股期概念': '与股指期货相关',
    '股权激励': '上市公司向高管/员工授予股票期权或限制性股票',
    '资产注入': '大股东将优质资产注入上市公司',
    '分拆上市': '上市公司将子公司独立分拆上市',
    '整体上市': '集团公司整体注入上市公司',
    '重组概念': '涉及资产重组、并购预期',
    '含B股': '同时发行 B 股（境内上市外资股，以外币认购交易）',
    '含H股': '同时在港交所发行 H 股上市',
    '含GDR': '发行全球存托凭证（Global Depositary Receipts），境外融资',
    'QFII重仓': '合格境外机构投资者（QFII）重仓持有',
    '基金重仓': '公募基金重仓持有',
    '社保重仓': '全国社保基金重仓持有',
    '券商重仓': '券商资管重仓持有',
    '信托重仓': '信托产品重仓持有',
    '保险重仓': '保险资金重仓持有',
    '外资背景': '有外资股东背景',
    '高校背景': '高校控股或参股',
    '央企50': '央企控股的 50 只代表性股票',
    '科创50': '科创板 50 只代表性股票指数成分',
    '融资融券': '可融资买入或融券卖出的标的',
    '业绩预升': '上市公司预告业绩上升',
    '业绩预降': '上市公司预告业绩下降',
    '三板精选': '新三板（全国股转系统）精选层股票',

    # ========== 地理 / 政策题材 ==========
    '三沙概念': '三沙市（南海诸岛）管辖范围内的相关上市公司',
    '上海本地': '上海本地股',
    '上海自贸': '上海自由贸易试验区相关',
    '京津冀': '京津冀协同发展国家战略',
    '前海概念': '深圳前海深港现代服务业合作区',
    '天津自贸': '天津自由贸易试验区',
    '海南自贸': '海南自由贸易港',
    '雄安新区': '河北雄安新区国家战略',
    '海峡西岸': '海峡西岸经济区（福建）',
    '成渝特区': '成渝统筹城乡综合改革试验区',
    '皖江区域': '皖江城市带承接产业转移示范区',
    '黄河三角': '黄河三角洲高效生态经济区',
    '长株潭': '长沙-株洲-湘潭城市群两型社会试验区',
    '陕甘宁': '陕甘宁革命老区振兴规划',
    '图们江': '图们江区域合作开发（东北亚开放）',
    '朝鲜改革': '朝鲜改革开放预期相关题材',
    '日韩贸易': '中日韩贸易相关',
    '东亚自贸': '东亚自由贸易区',
    '振兴沈阳': '振兴东北老工业基地',
    '武汉规划': '武汉城市规划相关',
    '沿海发展': '沿海经济发展战略',
    '海上丝路': '21 世纪海上丝绸之路',
    '深圳本地': '深圳本地股',
    '自贸区': '自由贸易试验区统称',
    '迪士尼': '上海迪士尼主题公园相关',
    '土地流转': '农村集体土地流转改革',
    '水域改革': '水域使用制度改革',

    # ========== 公司 / 品牌题材 ==========
    '华为概念': '与华为有合作或供应链关系',
    '华为汽车': '华为智能汽车（鸿蒙智行）相关',
    '华为海思': '华为海思芯片相关产业链',
    '华为鸿蒙': '华为鸿蒙操作系统相关',
    '鸿蒙概念': '鸿蒙 OS 生态合作伙伴',
    '苹果概念': '苹果公司供应链',
    '百度概念': '与百度有合作',
    '小米概念': '小米供应链',
    '特斯拉': '特斯拉供应链',
    '恒大概念': '中国恒大相关产业链',
    '参股金融': '参股银行/券商/保险等金融机构',

    # ========== 专业缩写 ==========
    'CRO概念': 'Contract Research Organization 合同研究组织，医药研发外包服务',
    'CXO概念': '医药外包服务总称（CRO+CDMO+CMO+CSO）',
    'HIT电池': 'Heterojunction with Intrinsic Thin-layer 异质结电池，高效太阳能电池技术',
    'BC电池': 'Back Contact 背接触电池，太阳能电池高效技术路线',
    'TOPCon': 'Tunnel Oxide Passivated Contact 隧穿氧化层钝化接触，N 型太阳能电池技术',
    '3D打印': '增材制造技术',
    '5G概念': '第五代移动通信技术产业链',

    # ========== 医药 / 生物 ==========
    '仿制药': '专利到期药品的仿制生产',
    '创新药': '原研创新药物',
    '免疫治疗': '肿瘤免疫疗法（PD-1/CAR-T 等）',
    '基因概念': '基因工程相关',
    '基因测序': 'DNA 测序技术与服务',
    '生物疫苗': '疫苗研发与生产',
    '生物育种': '生物技术育种',
    '生物燃料': '生物质能源（燃料乙醇、生物柴油）',
    '抗癌': '抗肿瘤药物',
    '甲型流感': '流感相关药物',
    '超级细菌': '应对耐药菌的抗生素类药物',
    '维生素': '维生素原料药生产',
    '民营医院': '民营医疗机构',
    '婴童概念': '婴童用品/教育/医疗，三孩政策受益',

    # ========== 新能源 / 储能 / 化工材料 ==========
    '钠电池': '钠离子电池，锂资源替代方案',
    '钒电池': '全钒液流电池，大规模长时储能',
    '钙钛矿': '钙钛矿太阳能电池，第三代光伏技术',
    '锂电池': '锂离子电池产业链',
    '锂矿': '锂资源采选',
    '盐湖提锂': '从盐湖卤水提锂',
    '氢能源': '氢燃料产业链',
    '氢燃料': '氢燃料电池',
    '页岩气': '页岩气开采',
    '风电': '风力发电',
    '风能': '风能利用',
    '光伏': '太阳能光伏发电',
    '地热能': '地热能开发',
    '核电核能': '核能发电',
    '石墨烯': '石墨烯新材料',
    '碳纤维': '碳纤维复合材料',
    '碳中和': '碳达峰碳中和"双碳"目标',
    '碳交易': '碳排放权交易市场',
    '聚氨酯': '聚氨酯化工材料',
    '电解液': '锂电池电解液',
    '草甘膦': '除草剂农药',
    '稀缺资源': '稀缺矿产资源（稀土、钨、锑等）',
    '新能源': '新能源产业总称',

    # ========== 半导体 / 电子 / 科技 ==========
    '物联网': 'Internet of Things 物联网',
    '网络游戏': '网络游戏研发与运营',
    '电商概念': '电子商务',
    '电子支付': '电子支付/第三方支付',
    '充电桩': '电动汽车充电桩',
    '高压快充': '高压平台快速充电技术',
    '无线耳机': 'TWS 真无线蓝牙耳机',
    '触摸屏': '触控屏',
    '安防服务': '安防监控',
    '信息安全': '网络安全',
    '宽带提速': '宽带提速工程',
    '卫星导航': '北斗等卫星导航',
    '大飞机': '国产大飞机 C919',
    '国产软件': '国产软件替代',
    '智能家居': '智能家居',
    '智能机器': '智能机器人',
    '智能电网': '智能电网',
    '智能穿戴': '可穿戴设备',
    '汽车电子': '汽车电子产品',

    # ========== 消费 / 农业 / 食品 ==========
    '白酒概念': '白酒生产销售',
    '猪肉': '生猪养殖',
    '鸡肉': '禽类养殖',
    '生态农业': '生态农业',
    '水产品': '水产养殖',
    '体育概念': '体育产业',
    '奢侈品': '奢侈品',
    '文化振兴': '文化产业振兴',
    '食品安全': '食品安全检测与监管',

    # ========== 环保 / 节能 / 资源 ==========
    '固废处理': '固体废物处理',
    '垃圾分类': '垃圾分类',
    '污水处理': '污水处理',
    '空气治理': '大气污染治理',
    '水利建设': '水利工程',
    '节能环保': '节能环保',
    '绿色照明': 'LED 绿色照明',
    '建筑节能': '建筑节能',
    '循环经济': '循环经济',
    '低碳经济': '低碳经济',
    '核污防治': '核污染治理',
    '海水淡化': '海水淡化',
    '海工装备': '海洋工程装备',
    '涉矿概念': '涉足矿产资源开发',

    # ========== 金融 / 改革 ==========
    '互联金融': '互联网金融',
    '民营银行': '民营银行',
    '金融参股': '参股金融机构',
    '金融改革': '金融体制改革',
    '油气改革': '油气体制改革',
    '专精特新': '专业化、精细化、特色化、新颖化的中小企业',
    '国企改革': '国有企业改革',
    '内贸规划': '国内贸易规划',
    '出口退税': '出口退税政策受益',
    '乡村振兴': '乡村振兴战略',

    # ========== 军工 / 航天 ==========
    '军工航天': '军工航天',
    '军民融合': '军民融合发展战略',
    '国防军工': '国防军工',

    # ========== 其他 ==========
    '博彩概念': '博彩产业（含澳门博彩、彩票）',
    '赛马概念': '赛马产业（海南赛马预期）',
    '超导概念': '超导材料',
}

# SINA_HEADERS imported from utils.http_constants


def _normalize_ts_code(code):
    """统一成分股代码为 ts_code 格式"""
    code = str(code).strip()
    if '.' in code:
        return code.upper()
    if code.startswith('6') or code.startswith('9'):
        return f'{code}.SH'
    elif code.startswith('8') or code.startswith('4') or code.startswith('92'):
        return f'{code}.BJ'
    else:
        return f'{code}.SZ'


def _sina_fetch_concept_list():
    """从新浪财经获取概念板块列表，返回 [(name, node, netamount), ...]"""
    url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk'
    items = []
    for page in range(1, 20):
        try:
            resp = requests.get(url, params={
                'page': page, 'num': 100, 'sort': 'netamount', 'asc': 0, 'fenlei': 1
            }, timeout=10, headers=SINA_HEADERS)
            data = resp.json()
            if not data:
                break
            for item in data:
                name = item.get('name', '').strip()
                node = item.get('category', '').strip()
                if name and node:
                    items.append({
                        'name': name,
                        'node': node,
                        'netamount': float(item.get('netamount', 0) or 0),
                    })
            if len(data) < 100:
                break
        except Exception as e:
            print(f'[sync_concept_sectors] sina list page {page} error: {e}')
            break
    # 按净流入排序，取前 200（避免成分股请求过多）
    items.sort(key=lambda x: x['netamount'], reverse=True)
    print(f'[sync_concept_sectors] fetched {len(items)} concept boards from sina')
    return items[:200]


def _sina_fetch_concept_cons(node, max_pages=10):
    """获取单个新浪概念板块的成分股 code 列表"""
    url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
    codes = []
    for page in range(1, max_pages + 1):
        try:
            resp = requests.get(url, params={
                'page': page, 'num': 80, 'sort': 'symbol', 'asc': 1, 'node': node
            }, timeout=10, headers=SINA_HEADERS)
            data = resp.json()
            if not data:
                break
            for item in data:
                code = str(item.get('code', '')).strip()
                if code and len(code) == 6 and code.isdigit():
                    codes.append(_normalize_ts_code(code))
            if len(data) < 80:
                break
        except Exception as e:
            print(f'[sync_concept_sectors] sina cons {node} page {page} error: {e}')
            break
    return codes


def fetch_from_sina():
    """从新浪财经拉取概念板块列表 + 成分股"""
    concepts = {}
    items = _sina_fetch_concept_list()
    if not items:
        return concepts

    def worker(item):
        codes = _sina_fetch_concept_cons(item['node'])
        return item['name'], codes, len(codes)

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(worker, item): item for item in items}
        for future in as_completed(futures):
            name, codes, count = future.result()
            if codes:
                concepts[name] = codes
                if count > 0 and count % 100 == 0:
                    print(f'[sync_concept_sectors] sina {name}: {count} stocks (may have more)')
    print(f'[sync_concept_sectors] sina concepts with constituents: {len(concepts)}')
    return concepts


def fetch_from_akshare():
    """从 AkShare 拉取东方财富概念板块及成分股"""
    try:
        import akshare as ak
    except ImportError:
        print('[sync_concept_sectors] akshare not installed')
        return {}

    concepts = {}
    try:
        df_list = ak.stock_board_concept_name_em()
        print(f'[sync_concept_sectors] fetched {len(df_list)} concept boards from akshare')
    except Exception as e:
        print(f'[sync_concept_sectors] akshare stock_board_concept_name_em error: {e}')
        return {}

    names = []
    for _, row in df_list.iterrows():
        name = row.get('板块名称', '').strip()
        if name:
            names.append(name)

    def worker(name):
        try:
            df_cons = ak.stock_board_concept_cons_em(symbol=name)
            codes = []
            for _, r in df_cons.iterrows():
                code = r.get('代码') or r.get('股票代码')
                if code:
                    codes.append(_normalize_ts_code(code))
            return name, codes
        except Exception as e:
            return name, []

    with ThreadPoolExecutor(max_workers=4) as executor:
        for name, codes in executor.map(worker, names):
            if codes:
                concepts[name] = codes
    print(f'[sync_concept_sectors] akshare concepts with constituents: {len(concepts)}')
    return concepts


def fetch_from_tushare_ths():
    """从 Tushare 同花顺概念接口拉取板块及成分股（需 ths_index/ths_member 权限）"""
    try:
        import tushare as ts
        from config import TUSHARE_TOKEN
        if not TUSHARE_TOKEN:
            print('[sync_concept_sectors] tushare token not configured')
            return {}
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()
    except Exception as e:
        print(f'[sync_concept_sectors] tushare init error: {e}')
        return {}

    concepts = {}
    try:
        # type=N 表示概念板块
        df_index = pro.ths_index(type='N', fields='ts_code,name,count')
        print(f'[sync_concept_sectors] fetched {len(df_index)} ths concept boards')
    except Exception as e:
        print(f'[sync_concept_sectors] tushare ths_index error: {e}')
        return {}

    def worker(row):
        ts_code = row.get('ts_code')
        name = row.get('name', '').strip()
        if not ts_code or not name:
            return name, []
        try:
            df_cons = pro.ths_member(ts_code=ts_code, fields='code,name')
            codes = []
            for _, r in df_cons.iterrows():
                code = r.get('code')
                if code:
                    codes.append(_normalize_ts_code(code))
            return name, codes
        except Exception:
            logger.debug(f"worker failed", exc_info=True)
            return name, []

    rows = df_index.to_dict('records')
    with ThreadPoolExecutor(max_workers=4) as executor:
        for name, codes in executor.map(worker, rows):
            if codes:
                concepts[name] = codes
    print(f'[sync_concept_sectors] tushare ths concepts with constituents: {len(concepts)}')
    return concepts


def fetch_from_eastmoney():
    """从东方财富 HTTP API 拉取概念板块列表（暂无免费成分股接口，仅作名称补充）"""
    url = 'http://push2.eastmoney.com/api/qt/clist/get'
    names = []
    for page in range(1, 5):
        try:
            resp = requests.get(url, params={
                'pn': page, 'pz': 100, 'po': 1, 'np': 1,
                'fltt': 2, 'invt': 2, 'fid': 'f12',
                'fs': 'm:90 t:3',
                'fields': 'f12,f14'
            }, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            data = resp.json()
            diff = data.get('data', {}).get('diff', {})
            if isinstance(diff, dict):
                diff = list(diff.values())
            if not diff:
                break
            for item in diff:
                name = item.get('f14', '').strip()
                if name and name not in names:
                    names.append(name)
        except Exception as e:
            print(f'[sync_concept_sectors] eastmoney page {page} error: {e}')
            break
    print(f'[sync_concept_sectors] fetched {len(names)} concept names from eastmoney')
    return names


def merge_concepts(*sources):
    """合并多源概念板块数据，优先使用成分股最多的来源。
    同时去重："X概念" 与 "X" 同时存在时，保留成分股更多的，删除另一个。
    """
    merged = {}
    for source_dict in sources:
        for name, codes in source_dict.items():
            name = name.strip()
            if not name:
                continue
            existing = merged.get(name, [])
            # 优先保留更长的成分股列表
            if len(codes) > len(existing):
                merged[name] = list(dict.fromkeys(codes))

    # 去重：处理 "X概念" 与 "X" 的重复对
    names = list(merged.keys())
    to_drop = set()
    for name in names:
        if name.endswith('概念'):
            base = name[:-2]
            if base in merged and base not in to_drop:
                # 保留成分股更多的
                if len(merged[base]) >= len(merged[name]):
                    to_drop.add(name)
                else:
                    to_drop.add(base)
    for name in to_drop:
        merged.pop(name, None)
    if to_drop:
        print(f'[sync_concept_sectors] dedup removed {len(to_drop)} duplicates: {sorted(to_drop)}')
    return merged


def sync():
    with get_db_session() as db:
        # 确保表存在
        Base.metadata.create_all(bind=engine, tables=[ConceptSector.__table__])

        # 1. 新浪：列表 + 成分股（主数据源）
        sina_concepts = fetch_from_sina()

        # 2. AkShare：列表 + 成分股
        akshare_concepts = fetch_from_akshare()

        # 3. Tushare THS：列表 + 成分股（需权限）
        tushare_concepts = fetch_from_tushare_ths()

        # 4. 东方财富：仅名称补充
        em_names = fetch_from_eastmoney()

        # 5. 合并：优先成分股最多的来源
        merged = merge_concepts(sina_concepts, akshare_concepts, tushare_concepts, FALLBACK_CONCEPTS)

        # 东财名称补充：如果某概念只有名称没有成分股，尝试从其他源找
        for name in em_names:
            if name not in merged:
                merged[name] = akshare_concepts.get(name) or tushare_concepts.get(name) or FALLBACK_CONCEPTS.get(name, [])

        now = datetime.now()
        synced = 0
        for name, codes in merged.items():
            codes_str = ','.join(codes)
            source = 'sina'
            if name in akshare_concepts:
                source = 'akshare_em'
            if name in tushare_concepts:
                source = 'tushare_ths'
            if name in FALLBACK_CONCEPTS and name not in sina_concepts and name not in akshare_concepts and name not in tushare_concepts:
                source = 'fallback'

            existing = db.query(ConceptSector).filter_by(name=name).first()
            if existing:
                existing.stocks = codes_str
                existing.stock_count = len(codes)
                existing.source = source
                existing.updated_at = now
            else:
                db.add(ConceptSector(
                    name=name,
                    source=source,
                    stocks=codes_str,
                    stock_count=len(codes),
                ))
            synced += 1
        db.commit()
        print(f'[sync_concept_sectors] synced {synced} concept sectors')

        # 清理 merged 中已不存在的旧概念板块及其资金流向数据
        valid_names = set(merged.keys())
        stale = db.query(ConceptSector).filter(~ConceptSector.name.in_(valid_names)).all()
        if stale:
            from db.models import ConceptSectorFlow, RealtimeConceptSectorFlow
            for s in stale:
                db.query(ConceptSectorFlow).filter_by(concept_sector_id=s.id).delete()
                db.query(RealtimeConceptSectorFlow).filter_by(concept_sector_id=s.id).delete()
                db.delete(s)
            db.commit()
            print(f'[sync_concept_sectors] cleaned {len(stale)} stale concept sectors')

        # 打印来源分布
        dist = db.query(ConceptSector.source, func.count(ConceptSector.id)).group_by(ConceptSector.source).all()
        print(f'[sync_concept_sectors] source distribution: {dist}')


if __name__ == '__main__':
    sync()
