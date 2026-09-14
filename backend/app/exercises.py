"""经典练习的章节、学科与显式知识点映射，不依赖 AI 猜测题目所属学科。"""
import re
from urllib.parse import urlparse


EXERCISE_BASE = 'https://www.csgraduates.com/study_methods/exercise/'
# 路径是来源的一部分；题号只在所属章节内唯一。
SECTIONS = {
    'data_structure/complexity': ('数据结构', '复杂度分析', '复杂度分析'),
    'data_structure/btree': ('数据结构', 'B 树', 'B树'),
    'data_structure/array': ('数据结构', '数组', '数组'),
    'data_structure/linked_list': ('数据结构', '链表', '链表'),
    'data_structure/queue': ('数据结构', '队列', '队列'),
    'data_structure/stack': ('数据结构', '栈', '栈'),
    'data_structure/binary_tree': ('数据结构', '二叉树', '树的概念'),
    'data_structure/graph': ('数据结构', '图', '图的概念'),
    'data_structure/hash': ('数据结构', '哈希表', '散列表'),
    'data_structure/sort': ('数据结构', '排序', '排序算法'),
    'architecture/number_repr': ('组成原理', '数制', '数制'),
    'architecture/storage': ('组成原理', '存储系统', '存储器概念'),
    'architecture/cpu': ('组成原理', 'CPU', '指令体系结构'),
    'architecture/pipeline': ('组成原理', '流水线', '流水线概念'),
    'architecture/io': ('组成原理', 'I/O', 'IO方式'),
    'os/memory': ('操作系统', '存储管理', '内存管理方式'),
    'os/process': ('操作系统', '进程管理', '进程概念'),
    'os/deadlock': ('操作系统', '死锁', '死锁概念'),
    'os/cpu_schedule': ('操作系统', 'CPU 调度', '处理机调度算法'),
    'network/physical_layer': ('计算机网络', '物理层', '物理层'),
    'network/datalink_layer': ('计算机网络', '数据链路层', '数据链路层'),
    'network/network_layer': ('计算机网络', '网络层', '网络层'),
    'network/transport_layer': ('计算机网络', '传输层', '传输层'),
    'network/application_layer': ('计算机网络', '应用层', '应用层'),
}

# 同义词只在该学科内使用。未出现明确细分概念时，保留章节标签。
ALIASES = {
    '数据结构': {
        'B+树': r'b[+＋]树', 'B树': r'b树|b-树',
        '二叉排序树': r'二叉搜索树|二叉查找树|bst',
        '二叉树遍历': r'先序|前序|中序|后序|层序|二叉树.*遍历|遍历.*二叉树',
        '二叉树构建': r'重建.*二叉树|构造.*二叉树|先序.*中序|前序.*中序|中序.*后序',
        '二叉树和森林的转换': r'森林.*二叉树|二叉树.*森林',
        '树和二叉树的转换': r'树.*转换.*二叉树|二叉树.*转换.*树',
        '二叉树存储': r'二叉树.*顺序存储|顺序存储.*二叉树',
        '平衡二叉树': r'avl|平衡二叉|二叉.*平衡',
        '完全二叉树': r'完全二叉树', '满二叉树': r'满二叉树',
        '哈夫曼树': r'哈夫曼树|赫夫曼树|huffman.*树',
        '哈夫曼编码': r'哈夫曼编码|赫夫曼编码|huffman.*编码',
        '堆的概念': r'最大堆|最小堆|大根堆|小根堆|大顶堆|小顶堆|堆排序',
        '散列表': r'哈希|散列|hash',
        '图的遍历': r'广度优先|深度优先|bfs|dfs',
        '最小生成树': r'最小生成树|最小代价生成树|prim|kruskal',
        '最短路径': r'最短路径|最短路|dijkstra|floyd',
        '拓扑排序': r'拓扑', '关键路径': r'关键路径|关键活动|aoe',
        '队列': r'队列', '链表': r'链表|链式存储',
        '二维数组': r'二维数组|二维.*数组|行优先|列优先',
        '特殊矩阵': r'稀疏矩阵|对称矩阵|三角矩阵|三对角',
        '三元组表': r'三元组', '入栈出栈序列': r'出栈.*序列|出栈.*顺序|弹出.*序列',
        '中缀转后缀': r'中缀.*后缀|后缀.*中缀',
        '后序表达式求值': r'后缀.*求值|逆波兰.*求值',
        '快速排序': r'快速排序|快排', '归并排序': r'归并',
        '插入排序': r'插入排序', '外部排序': r'外部排序|外排序',
    },
    '组成原理': {
        '补码': r'补码', '无符号数': r'无符号|unsigned',
        '类型转换': r'类型转换|强制转换|符号扩展|零扩展|int.*short|short.*int|float.*int|int.*float',
        'IEEE浮点数表示': r'ieee|浮点.*表示|浮点.*格式|浮点.*范围',
        '浮点数加减': r'浮点.*运算|浮点.*加|浮点.*减|对阶|规格化|舍入',
        'cache概念': r'cache|高速缓存|高速缓冲',
        'cache映射方式': r'相联|组关联|直接映射|缓存.*组|cache.*组',
        'cache写策略': r'写回|回写|写直达|直写|writeback|writethrough',
        '存储器概念': r'sram|dram|rom|ram',
        '主存容量的扩展': r'存储.*芯片|芯片.*存储|位扩展|字扩展',
        '存储器地址': r'存储.*地址|地址线|数据线',
        '指令寻址方式': r'寻址方式|有效地址|指令.*寻址|立即寻址|直接寻址|间接寻址|变址寻址|基址寻址|相对寻址|寄存器寻址',
        '指令格式': r'指令.*位|操作码|指令格式',
        '操作码扩展编码': r'扩展操作码|操作码扩展',
        '复杂和精简指令集': r'risc|cisc|精简指令|复杂指令',
        '控制器种类': r'硬布线|微程序|微指令',
        '微程序控制器': r'微程序|微指令|控制存储器',
        '寄存器类型': r'程序计数器|累加器|指令寄存器|地址寄存器|数据寄存器',
        '计算机性能指标': r'cpi|mips|时钟频率|主频|执行时间|加速比',
        '流水线概念': r'流水线', '流水线冒险': r'冒险|数据相关|结构相关|控制相关|数据依赖|分支预测|旁路',
        'DMA': r'dma|直接存储器访问', '中断IO': r'中断',
        '异常和中断': r'中断|异常|陷阱', 'IO方式': r'输入输出|i/o|程序查询|轮询',
        '总线概念': r'总线', '总线定时': r'同步总线|异步总线|握手',
        '磁盘性能指标': r'寻道|旋转延迟|磁盘.*时间',
        '地址翻译': r'虚拟地址|虚地址|物理地址', '虚拟页式管理': r'分页|页表|缺页',
        '运算电路': r'加法器|乘法器|alu', '逻辑移位': r'逻辑.*移位|算术.*移位',
    },
    '操作系统': {
        '死锁概念': r'死锁', '死锁产生的必要条件': r'死锁.*条件|循环等待|请求和保持|占有并等待',
        '死锁的处理方法': r'死锁.*检测|死锁.*解除|死锁.*避免|死锁.*预防',
        '死锁预防': r'死锁.*预防|预防.*死锁',
        '银行家算法': r'银行家|安全序列|安全状态|不安全状态',
        '信号量': r'信号量|semaphore|p\(|v\(|wait\(|signal\(',
        '进程的互斥': r'互斥|临界区', '临界资源': r'临界资源',
        '软件互斥算法': r'peterson|dekker', '硬件互斥指令': r'test.?and.?set|compare.?and.?swap|swap指令',
        '管程': r'管程|monitor', '进程间通信': r'进程间通信|管道|消息传递|共享内存',
        '进程和线程': r'线程|thread', '进程概念': r'fork\(|进程控制块|pcb',
        '进程状态': r'就绪|阻塞|进程.*状态',
        '用户级和内核级线程': r'用户级线程|内核级线程|用户线程|内核线程',
        '处理机调度算法': r'处理机调度|cpu调度|进程调度|作业调度|sjf|srtf|短作业优先|短进程优先|响应比|时间片',
        '时间片轮转': r'时间片|轮转|roundrobin', '调度指标': r'周转时间|等待时间|响应时间',
        '用户态和内核态': r'用户态|内核态|核心态|特权|系统态',
        '系统调用': r'系统调用', '操作系统概念': r'操作系统|批处理|多道程序|并行|并发',
        '内存管理方式': r'内存管理|存储管理|分区|分页|分段|段式|页式',
        '段式内存管理': r'分段|段式|段表', '动态分区分配': r'最佳适应|首次适应|最坏适应|伙伴系统|外部碎片',
        '虚拟页式管理': r'分页|页式|虚拟内存|虚拟存储|页表|缺页',
        '页表': r'页表', 'TLB': r'tlb|快表|转换后备',
        '地址翻译': r'虚拟地址|逻辑地址|物理地址|地址转换|地址映射',
        '页面置换算法': r'页面置换|页替换|页面替换|lru|最优.*置换|(?:页面|页框|缺页).*(?:fifo|optimal)|(?:fifo|optimal).*(?:页面|页框|缺页)',
        'LRU': r'lru|最近最少使用', 'clock算法': r'clock|时钟.*置换|第二次机会',
        'Belady异常': r'belady|belady异常', '缺页异常': r'缺页',
        '抖动': r'抖动|颠簸|thrashing',
        '磁盘调度算法': r'磁盘调度|寻道|sstf|scan|c-look|look算法',
        'inode': r'inode|索引结点|索引节点|文件控制块', '文件链接': r'硬链接|软链接|符号链接',
    },
    '计算机网络': {
        'TCP拥塞控制': r'拥塞|慢启动|aimd|ssthresh',
        'TCP滑动窗口': r'tcp.*窗口|接收窗口|发送窗口|流量控制',
        'TCP三次握手': r'三次握手|tcp.*建立|建立.*tcp|syn',
        'TCP四次挥手': r'四次挥手|tcp.*释放|tcp.*关闭|time.?wait',
        'TCP首部': r'tcp.*首部|tcp.*头部|tcp.*序号|tcp.*序列号',
        'UDP': r'udp', 'ARQ协议': r'arq|gbn|sr协议|回退n|选择重传|选择性重传|停等|停止等待|滑动窗口',
        'CSMA/CD': r'csma/cd|载波侦听.*冲突|载波监听.*冲突|冲突检测|碰撞检测|二进制.*退避',
        'CSMA/CD限制条件': r'最小帧长|最短帧长|争用期|争用时间',
        'CSMA/CA': r'csma/ca|碰撞避免|冲突避免', 'CDMA': r'cdma|码分多址',
        '差错控制': r'差错|校验|检错|纠错', '循环冗余码': r'crc|循环冗余',
        '海明距离': r'海明|汉明|hamming',
        '调制方法': r'调制|qam|psk|ask|fsk|波特',
        '奈奎斯特定理': r'奈奎斯特|奈氏|nyquist|无噪声|无噪音',
        '香农定理': r'香农|shannon|信噪比', '编码方法': r'曼彻斯特|nrz|编码',
        '信道利用率': r'信道利用率|信道效率|链路利用率|协议.*效率',
        '传输介质': r'双绞线|光纤|同轴电缆',
        '以太网': r'以太网|ethernet|802\.3', 'MAC地址': r'mac地址|物理地址',
        '交换机': r'交换机|网桥', 'VLAN': r'vlan',
        'ARP': r'(?<![a-z])arp(?![a-z])|地址解析',
        'IP数据报分片': r'分片|mtu|片偏移', '子网划分': r'子网|掩码|cidr',
        '子网聚合': r'聚合|路由汇总', '最长前缀匹配': r'最长.*匹配|最长前缀',
        '路由协议': r'ospf|rip|bgp|路由协议',
        '距离向量算法': r'距离向量|距离矢量|bellman',
        '路由器': r'路由器', '路由表': r'路由表',
        'IPv6': r'ipv6', 'NAT': r'(?<![a-z])nat(?![a-z])|地址转换',
        'ICMP': r'icmp|ping|traceroute', 'DHCP': r'dhcp',
        'FTP': r'ftp', 'DNS': r'dns|域名', 'HTTP': r'https?|web|网页',
        '电子邮件': r'电子邮件|smtp|pop3|imap',
        'OSI模型': r'osi|七层', 'TCP/IP模型': r'tcp/ip',
        '网络应用模型': r'客户.*服务器|客户端.*服务端|p2p|对等',
    },
}


def section_from_url(url):
    return urlparse(url or '').path.removeprefix('/study_methods/exercise/').strip('/')


def source_label(source, year, url=''):
    if source == 'exercise':
        section = SECTIONS.get(section_from_url(url))
        return '经典练习' + (f' · {section[1]}' if section else '')
    if source == 'simulate':
        return f'模拟卷 {year}'
    return f'{year} 年真题'


def classify(section, stem, options, explanation, vocabulary=()):
    subject, _title, fallback = SECTIONS[section]
    compact = lambda text: re.sub(r'\s+', '', text or '').lower()
    stem_text = compact(stem)
    option_text = compact(' '.join(options))
    patterns = {tag: re.escape(compact(tag)) for tag in vocabulary}
    patterns.update(ALIASES.get(subject, {}))
    if section != 'data_structure/graph':
        for tag in ('图的遍历', '最小生成树', '最短路径', '拓扑排序', '关键路径'):
            patterns.pop(tag, None)
    # 题干优先，其次选项；解析中的旁支概念不能反过来决定本题考点。
    tags = [tag for tag, pattern in patterns.items() if re.search(pattern, stem_text, re.I)]
    if not tags:
        tags = [tag for tag, pattern in patterns.items() if re.search(pattern, option_text, re.I)]
    if section in ('data_structure/sort', 'data_structure/complexity') and fallback not in tags:
        tags.append(fallback)
    return sorted(set(tags or [fallback]))
