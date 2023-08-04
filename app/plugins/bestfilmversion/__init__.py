import datetime
from pathlib import Path
from threading import Lock
from typing import Optional, Any, List, Dict, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.chain.subscribe import SubscribeChain
from app.core.config import settings
from app.core.context import MediaInfo
from app.core.event import Event
from app.core.event import eventmanager
from app.core.metainfo import MetaInfo
from app.log import logger
from app.modules.emby import Emby
from app.modules.jellyfin import Jellyfin
from app.modules.plex import Plex
from app.plugins import _PluginBase
from app.schemas.types import EventType, MediaType
from app.utils.http import RequestUtils

lock = Lock()


class BestFilmVersion(_PluginBase):

    # 插件名称
    plugin_name = "收藏洗版"
    # 插件描述
    plugin_desc = "jellyfin|emby点击收藏后,自动订阅洗版(只支持电影洗版)"
    # 插件图标
    plugin_icon = "like.jpg"
    # 主题色
    plugin_color = "#05B711"
    # 插件版本
    plugin_version = "1.0"
    # 插件作者
    plugin_author = "wlj"
    # 作者主页
    author_url = "https://github.com/developer-wlj"
    # 插件配置项ID前缀
    plugin_config_prefix = "bestversion_"
    # 加载顺序
    plugin_order = 3
    # 可使用的用户级别
    auth_level = 2

    # 私有变量
    _scheduler: Optional[BackgroundScheduler] = None
    _cache_path: Optional[Path] = None
    subscribechain = None
    jellyfin = None
    jellyfin_user = None
    emby = None
    emby_user = None
    plex = None
    plex_user = None
    service_host = None
    service_apikey = None

    # 配置属性
    _enabled: bool = False
    _cron: str = ""
    _notify: bool = False

    def init_plugin(self, config: dict = None):
        self._cache_path = settings.TEMP_PATH / "__best_version_cache__"
        self.subscribechain = SubscribeChain()
        if settings.MEDIASERVER =='jellyfin' or settings.MEDIASERVER =='JELLYFIN':
            self.jellyfin = Jellyfin()
            self.jellyfin_user=self.jellyfin.get_user()
            self.service_apikey=settings.JELLYFIN_API_KEY
            self.service_host=settings.JELLYFIN_HOST
        if settings.MEDIASERVER =='emby' or settings.MEDIASERVER =='EMBY':
            self.emby = Emby()
            self.emby_user = self.emby.get_user()
            self.service_apikey = settings.EMBY_API_KEY
            self.service_host = settings.EMBY_HOST
        if settings.MEDIASERVER =='plex' or settings.MEDIASERVER =='PLEX':
            self.emby = Plex()
            self.service_apikey = settings.PLEX_TOKEN
            self.service_host = settings.PLEX_HOST
        if self.service_host:
            if not self.service_host.endswith("/"):
                self.service_host += "/"
            if not self.service_host.startswith("http"):
                self.service_host = "http://" + self.service_host


        # 停止现有任务
        self.stop_service()

        # 配置
        if config:
            self._enabled = config.get("enabled")
            self._cron = config.get("cron")
            self._notify = config.get("notify")

        if self._enabled:

            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            if self._cron:
                try:
                    self._scheduler.add_job(func=self.sync,
                                            trigger=CronTrigger.from_crontab(self._cron),
                                            name="收藏洗版")
                except Exception as err:
                    logger.error(f"定时任务配置错误：{err}")
                    # 推送实时消息
                    self.systemmessage.put(f"执行周期配置错误：{err}")
            else:
                self._scheduler.add_job(self.sync, "interval", minutes=30, name="收藏洗版")

            # 启动任务
            if self._scheduler.get_jobs():
                self._scheduler.print_jobs()
                self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """
        定义远程控制命令
        :return: 命令关键字、事件、描述、附带数据
        """
        return [{
            "cmd": "/best_version",
            "event": EventType.BestVersion,
            "desc": "收藏洗版",
            "data": {}
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        """
        获取插件API
        [{
            "path": "/xx",
            "endpoint": self.xxx,
            "methods": ["GET", "POST"],
            "summary": "API说明"
        }]
        """
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式，留空自动'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'queue_cnt',
                                            'label': '队列数量'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "notify": True,
            "cron": "*/30 * * * *",
            "queue_cnt": 5
        }

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        # 查询同步详情
        historys = self.get_data('history')
        if not historys:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        # 数据按时间降序排序
        historys = sorted(historys, key=lambda x: x.get('time'), reverse=True)
        # 拼装页面
        contents = []
        for history in historys:
            title = history.get("title")
            poster = history.get("poster")
            mtype = history.get("type")
            time_str = history.get("time")
            overview = history.get("overview")
            tmdbid = history.get("tmdbid")
            contents.append(
                {
                    'component': 'VCard',
                    'content': [
                        {
                            'component': 'div',
                            'props': {
                                'class': 'd-flex justify-space-start flex-nowrap flex-row',
                            },
                            'content': [
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'VImg',
                                            'props': {
                                                'src': poster,
                                                'height': 120,
                                                'width': 80,
                                                'aspect-ratio': '2/3',
                                                'class': 'object-cover shadow ring-gray-500',
                                                'cover': True
                                            }
                                        }
                                    ]
                                },
                                {
                                    'component': 'div',
                                    'content': [
                                        {
                                            'component': 'VCardSubtitle',
                                            'props': {
                                                'class': 'pa-2 font-bold break-words whitespace-break-spaces'
                                            },
                                            'content': [
                                                {
                                                    'component': 'a',
                                                    'props': {
                                                        'href': f"https://www.themoviedb.org/movie/{tmdbid}",
                                                        'target': '_blank'
                                                    },
                                                    'text': title
                                                }
                                            ]
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'类型：{mtype}'
                                        },
                                        {
                                            'component': 'VCardText',
                                            'props': {
                                                'class': 'pa-0 px-2'
                                            },
                                            'text': f'时间：{time_str}'
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            )

        return [
            {
                'component': 'div',
                'props': {
                    'class': 'grid gap-3 grid-info-card',
                },
                'content': contents
            }
        ]

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))

    def sync(self):
        """
        通过流媒体管理工具收藏,自动洗版
        """

        # 读取缓存
        caches = self._cache_path.read_text().split("\n") if self._cache_path.exists() else []
        # 读取历史记录
        history = self.get_data('history') or []

        resp=None
        if self.jellyfin:
            # 根据加入日期 降序排序
            url=self.service_host+'Users/'+self.jellyfin_user+'/Items?SortBy=DateCreated%2CSortName&SortOrder=Descending&Filters=IsFavorite&Recursive=true&Fields=PrimaryImageAspectRatio%2CBasicSyncInfo&CollapseBoxSetItems=false&ExcludeLocationTypes=Virtual&EnableTotalRecordCount=false&Limit=20&apikey='+self.service_apikey
            # 获取收藏数据
            resp=self.media_simple_filter(url)

        elif self.emby:
            # 根据加入日期 降序排序
            url = self.service_host + 'emby/Users/' + self.emby_user+'/Items?SortBy=DateCreated%2CSortName&SortOrder=Descending&Filters=IsFavorite&Recursive=true&Fields=PrimaryImageAspectRatio%2CBasicSyncInfo&CollapseBoxSetItems=false&ExcludeLocationTypes=Virtual&EnableTotalRecordCount=false&Limit=20&api_key=' + self.service_apikey
            # 获取收藏数据
            resp = self.media_simple_filter(url)

        elif self.plex:
            # TODO plex待开发
            return

        for data in resp:
            # 检查缓存
            if data.get('Name') in caches:
                continue

            # 获取详情
            item_info_resp = None
            if self.jellyfin:
                item_info_resp = self.jellyfin.get_iteminfo(itemid=data.get('Id'))
            elif self.emby:
                item_info_resp = self.emby.get_iteminfo(itemid=data.get('Id'))
            elif self.plex:
                # TODO plex待开发
                item_info_resp = self.plex.get_iteminfo(itemid=data.get('Id'))

            if not item_info_resp:
                continue
            # 只接受Movie类型
            if data.get('Type') != 'Movie':
                continue

            # 获取tmdb_id
            media_info_ids=item_info_resp.get('ExternalUrls')
            for media_info_id in media_info_ids:
                if 'TheMovieDb' != media_info_id.get('Name'):
                    continue
                tmdb_find_id=str(media_info_id.get('Url')).split('/')
                tmdb_find_id.reverse()
                tmdb_id=tmdb_find_id[0]

                # 根据tmdbID获取数据
                tmdbinfo: Optional[dict] = self.chain.tmdb_info(tmdbid=tmdb_id,mtype=MediaType.MOVIE)
                if not tmdbinfo:
                    logger.warn(f'未获取到tmdb信息，标题：{data.get("Name")}，豆瓣ID：{tmdb_id}')
                    continue
                logger.info(f'获取到tmdb信息，标题：{data.get("Name")}，tmdbID：{tmdb_id}')

                # 识别媒体信息
                meta = MetaInfo(tmdbinfo.get("original_title") or tmdbinfo.get("title"))
                if tmdbinfo.get("year"):
                    meta.year = tmdbinfo.get("year")
                mediainfo: MediaInfo = self.chain.recognize_media(meta=meta)
                if not mediainfo:
                    logger.warn(f'未识别到媒体信息，标题：{data.get("Name")}，tmdbID：{tmdb_id}')
                    continue

                # 添加订阅
                self.subscribechain.add(mtype=MediaType.MOVIE,
                                        title=mediainfo.title,
                                        year=mediainfo.year,
                                        tmdbid=mediainfo.tmdb_id,
                                        best_version=True,
                                        username="收藏洗版",
                                        exist_ok=True)
                # 加入缓存
                caches.append(data.get('Name'))
                # 存储历史记录
                if mediainfo.tmdb_id not in [h.get("tmdbid") for h in history]:
                    history.append({
                        "title": tmdbinfo.get("title") or mediainfo.title,
                        "type": mediainfo.type.value,
                        "year": mediainfo.year,
                        "poster": mediainfo.get_poster_image(),
                        "overview": mediainfo.overview,
                        "tmdbid": mediainfo.tmdb_id,
                        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
        # 保存历史记录
        self.save_data('history', history)
        # 保存缓存
        self._cache_path.write_text("\n".join(caches))

    @staticmethod
    def media_simple_filter(url):
        try:
            resp = RequestUtils().get_res(url=url)
            if resp:
                return resp.json().get("Items")
            else:
                logger.error(f"User/Items 未获取到返回数据")
                return []
        except Exception as e:
            logger.error(f"连接User/Items 出错：" + str(e))
            return []

    @eventmanager.register(EventType.BestVersion)
    def remote_sync(self, event: Event):
        """
        收藏洗版
        """
        if event:
            logger.info("收到命令，开始执行收藏洗版 ...")
            self.post_message(channel=event.event_data.get("channel"),
                              title="开始执行收藏洗版 ...",
                              userid=event.event_data.get("user"))
        self.sync()

        if event:
            self.post_message(channel=event.event_data.get("channel"),
                              title="收藏洗版执行完成！", userid=event.event_data.get("user"))