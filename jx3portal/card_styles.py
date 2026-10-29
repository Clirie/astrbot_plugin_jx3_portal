"""名片生图模板库（可后台增删改 ✅）

从咩咩插件移植 ✅ 默认 16 个模板，存成 JSON，支持运行时修改。
"""

from __future__ import annotations

import json
import pathlib
import threading
import time
from typing import Any

DEFAULT_STYLES: list[dict[str, Any]] = [
    {'key': 'menpai', 'label': '门派史诗海报', 'enabled': True, 'order': 1, 'prompt': '以参考图角色为原型，为剑网三{force}角色「{name}」绘制门派史诗海报。保留角色面部轮廓、发型发色、服装结构与主配色、标志性配饰。延续侧脸剪影构图：明暗分明的侧脸与肩部轮廓形成视觉中心，用轮廓光勾出发丝和衣料边缘，面部保留少量可辨识的细节。背景用该门派标志性场景和徽纹构成远近层次，门派主题色用于环境光，不覆盖角色本身的服装颜色。电影海报式的大块明暗、精细CG材质；顶部保留舒展的负空间。只输出海报画面，不添加标题、文字、印章或水印。', 'negative': '文字，印章，水印，陌生人物，角色换装，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'yanjingtiao', 'label': '眼睛条横幅', 'enabled': True, 'order': 2, 'prompt': '制作横向宽幅眼睛条海报，严格沿用“双眼大特写背景＋中央半身人物＋发光画框”的叠层构图。两层都来自参考图的同一角色，保持发色、瞳色、眼型、眼距、妆造和服饰一致。背景为深色水平扫描线与霓虹光带；发光圆角矩形画框占据画面主体，框内铺满角色双眼的正面大特写，清楚表现睫毛、眼影、卧蚕与发丝，加强闪粉和瞳孔高光。前景放置去除原背景的半身人物，居中位于双眼之间，沿用参考图人物姿态与角度；前景人物清楚完整，后层双眼在其两侧仍可辨认。用细轮廓光区分前后层，光带避开瞳孔及前景面部。保持高饱和、闪亮、精致的广告海报质感，不加文字或水印。', 'negative': '文字，水印，双层角色长相不一致，眼睛错位，脸部过曝，多余肢体', 'size': '1536x608', 'final_size': '860x340'},
    {'key': 'shuimo', 'label': '水墨', 'enabled': True, 'order': 3, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。绘制宣纸上的水墨国风人物插画。人物面部与服装关键纹样用细笔交代，衣袂边缘以干笔飞白融入泼墨；长发、衣料与配饰沿用参考图，不额外添加花钿或改变衣服款式。远山古亭用淡墨，梅竹作为边缘点景，墨色由近浓到远淡；金箔与金漆碎屑少量点在背景和衣袂周围。面部保持干净，墨点不落在五官上。人物与左侧留白平衡，左侧毛笔竖题「{name}」，笔锋有提按和飞白，仅写此姓名，不加印章、落款或其他文字。', 'negative': '水印，印章，额外题字，错字，脸上墨点，服装改款，塑料皮肤，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'gongbi', 'label': '工笔重彩', 'enabled': True, 'order': 4, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。绘制工笔重彩人物画，沿用人物姿态，以细而有提按的线条勾勒五官、发丝、衣褶和饰物，矿物颜料逐层罩染，衣料转折柔和，纹样清楚。服装原有金属饰边用细金线点出。绢本暖底、缠枝纹样作低对比背景，人物面部和上身最清晰，边缘纹样疏密有序。呈现细腻线描与沉着重彩，不画成厚涂或摄影。画面不添加文字、印章、水印。', 'negative': '文字，印章，水印，粗黑描边，塑料质感，陌生人物，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'dunhuang', 'label': '敦煌壁画', 'enabled': True, 'order': 5, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。转换为敦煌壁画人物绘画，以流畅线描和矿物平涂塑造角色，土红、石青、石绿与赭金协调铺陈；角色衣装仍保留原有主色。飞天飘带在人物外围组织弧线，莲花纹样疏密交错，围绕主体形成庄重的装饰构图。墙体有细微斑驳、颜料剥落与岁月磨损，肌理主要落在背景，脸部线条清楚。保留原有衣冠与穿着，不改成飞天服饰，不额外加人物或肢体。无文字、印章或水印。', 'negative': '文字，水印，额外人物，额外手臂，改换服装，脸部破损，霓虹光效', 'size': '', 'final_size': ''},
    {'key': 'dongman', 'label': '日系动漫', 'enabled': True, 'order': 6, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。绘制日系动漫人物插画，用干净线稿、清晰的赛璐璐色块和两到三层阴影塑造体积；眼睛适度动画化，但保留原有眼型与神情，头发分束清楚，配饰简化后仍可辨认。主体占画面主要位置，保持参考图动作，以柔和侧光突出脸部。背景用与服装配色协调的简洁环境和少量虚化细节，边缘与人物轮廓分离。画面清透，五官清楚，不加文字、标识或水印。', 'negative': '文字，水印，陌生人物，服装改款，眼睛过大，厚重油画笔触，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'xinhaicheng', 'label': '新海诚', 'enabled': True, 'order': 7, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。转为新海诚动画电影式插画：澄澈的高饱和天空、具有体积的积云和细腻远景，逆光穿过云隙，发梢与衣缘形成明亮轮廓。人物用干净动画线稿与通透上色，面部仍有清楚的明暗，光斑只落在画面边缘。近处人物、中景草木或建筑、远处天空形成空间层次；环境暖光与蓝色阴影呼应，场景保持剑网三的古风语境。主体清晰，不被天空压成小人；不添加文字或水印。', 'negative': '文字，水印，脸部过曝，光斑遮脸，现代校服，现代城市，人物过小，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'jibuli', 'label': '吉卜力', 'enabled': True, 'order': 8, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。绘制吉卜力动画式手绘画面。人物用柔和但清楚的线条和简洁色块，表情自然；背景以水粉般的手绘笔触描绘绿意、树影与古风生活场景。阳光透过枝叶，暖肤色与草木绿协调，服装仍保持角色原有配色和纹样特征。细节集中在角色与附近景物，远景概括，呈现温暖、安静、有生活气息的动画镜头。人物比例符合原角色，不自动幼化；不添加文字或水印。', 'negative': '文字，水印，陌生人物，自动变成儿童，塑料3D质感，强烈霓虹，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'qban', 'label': 'Q版', 'enabled': True, 'order': 9, 'prompt': '以参考图角色为原型，绘制二头身Q版全身人物，保留发型轮廓、发色、瞳色、服装主配色及最有辨识度的配饰。头大身小、圆润脸型和明亮大眼，动作简化但有重心；衣服概括成清楚的几块结构，小装饰取舍有序，仍能一眼认出原角色。柔光、干净线条、轻盈糖果色，以服装主色搭配低饱和背景。单个人物居中，完整露出头饰与双脚，周围留出均匀空隙。可爱而非婴儿形象，不加文字、标签、印章或水印。', 'negative': '文字，水印，写实成人比例，多个人物，服装变款，头饰裁切，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'shouban', 'label': '树脂手办', 'enabled': True, 'order': 10, 'prompt': '拍摄一尊精密彩绘树脂手办，竖幅产品陈列照。参考图只用于角色外形：脸型、发色、发髻、原衣装配色和饰物都须还原；把全部表面转换成微缩模型材质。头发与毛领为清楚的硬质雕刻分束，只有刻线，没有真发和毛皮纤维；衣装为哑光树脂褶皱与局部金属漆，皮肤为平滑手工涂装，不出现毛孔或真人皮肤。制作完整的头、躯干、双腿和靴子，半身参考未展示的下装按原衣装延续补全，双脚站立于小型透明底座，禁止胸像。以轻微俯视的三分之四角度展示约25厘米高的模型，头脚底座全部入镜，占画面高度70%，桌面和背景明确表现微缩尺度。左后方包装盒退后虚化，脸部不重复成为焦点；纱幔玫瑰蕾丝只在边缘。中性明亮柔光，深灰背景，白色台面，雕刻细节清楚。无文字水印。', 'negative': '半身胸像，腰部截断，无腿，无脚，真人毛发，真实毛皮，真人皮肤，主体遮挡，包装盒抢主体，多余肢体，文字，水印', 'size': '1728x2304', 'final_size': ''},
    {'key': 'youhua', 'label': '古典油画', 'enabled': True, 'order': 11, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。绘制古典油画肖像，沿用人物朝向与神情，面部和双眼为视觉中心。伦勃朗式侧光照亮面颊，暗侧仍保留五官结构；以薄罩染处理肤色，厚笔触集中在衣褶、饰物高光和背景。暗赭、深褐背景衬托角色原有服装色彩，冷暖过渡自然，画布肌理细微可见。保持古风衣装，不改成欧洲礼服；只呈现绘画本身，不添加画框、文字、签名或水印。', 'negative': '文字，签名，水印，欧洲服装，塑料皮肤，黑暗吞没五官，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'shuicai', 'label': '清透水彩', 'enabled': True, 'order': 12, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。绘制清透水彩人物画，在白色水彩纸上以透明薄色层叠，背景和衣袂外围湿画晕染，脸部、眼睛、发饰用干画法收清边缘。服装原色形成主要色块，阴影保留透光感；纸白参与高光，边缘有自然水痕和细小色素沉积。主体实、周围虚，保留舒展留白，色彩轻盈但五官不淡到看不清。水渍与飞溅留在背景，不落在脸部；不添加文字、签名或水印。', 'negative': '文字，签名，水印，脸部水渍，五官模糊，厚重不透明颜料，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'jiaopian', 'label': '复古胶片', 'enabled': True, 'order': 13, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。转换为复古35mm胶片人像摄影，按原角色体型与年龄感呈现，古风衣装、妆造和配饰保持原样。人物自然处于古风庭院或木窗边，柔和自然光照亮面部；暖色高光与略偏青的阴影形成细微色偏，肤色自然。使用细颗粒、柔和高光溢出和轻微暗角，清晰焦点落在双眼与面部，背景浅景深。保留皮肤和织物细节，不过度磨皮；无胶片边框、日期戳、文字或水印。', 'negative': '文字，日期戳，水印，现代换装，陌生人物，过粗颗粒，过度磨皮，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'taluo', 'label': '塔罗牌', 'enabled': True, 'order': 14, 'prompt': '以参考图中的角色为唯一人物原型，保留其面部辨识特征、性别与年龄感、发型发色、服装结构和主配色、标志性配饰；只转换画风与场景。将角色绘制成独立塔罗牌卡面，人物居中，姿态端正且有叙事感；以清楚线稿、细腻平涂和少量层染呈现，保持原有衣冠。四周对称的细金线边框与卷草纹饰包围主体，星辰、月相和几何符号在背景组织层次，饰纹避开脸部。深色底与旧金、角色服装主色相互呼应，人物比背景更明亮。呈现单张完整卡面，边框不压住头饰，不堆叠多张牌；不添加牌名、数字、文字或水印。', 'negative': '文字，数字，水印，多张卡牌，边框遮脸，装饰遮挡人物，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'saibo', 'label': '赛博朋克', 'enabled': True, 'order': 15, 'prompt': '赛博朋克风格，霓虹光效与全息投影，未来都市感，保留角色配色特征', 'negative': '文字, 水印, 低画质', 'size': '', 'final_size': ''},
    {'key': 'xiangsu', 'label': '像素艺术', 'enabled': True, 'order': 16, 'prompt': '以参考图角色为原型，绘制16bit游戏风格的像素角色插画。保留发型剪影、发色、服装主配色、标志性武器和配饰，五官概括为少量清楚像素。单个人物完整置于简洁古风场景，姿态有重心，主体轮廓与背景分开。以统一像素网格、有限色阶、成组像素和少量抖动表现体积；细节集中在脸部、衣装色块和配饰。采用整数倍放大的硬边像素观感，不把普通插画叠成马赛克滤镜，不用平滑渐变或模糊边缘。无文字、界面、标识或水印。', 'negative': '文字，水印，模糊，平滑渐变，混杂像素尺寸，照片马赛克，多余肢体', 'size': '', 'final_size': ''},
    {'key': 'jianghu_cover', 'label': '江湖杂志封面', 'enabled': True, 'order': 17, 'prompt': '将参考角色设计成竖版江湖杂志封面，保留五官、发型、原有衣装配色与配饰，重构镜头和环境。人物脸部在上半部中央，脸与肩胸占画面三分之二，夕阳轮廓光照亮发丝衣甲，面部明亮清晰。前景朱红绸带斜掠下缘，中景人物，远景古城楼与旗帜，暖金天空衬托深色衣装，形成红、黑、金的强烈色彩层次。排版只含以下四处文字，每句只出现一次：顶部横排巨幅金色飞白书法“剑网三”；右侧中下部大书法“{name}”；姓名下方小号宋体“{force}”；左下两行书法“此身即江湖”“不负此行”。文字环绕人物不挡脸，刊头最大、姓名次之、门派最小，疏密错落，留出阅读间隙。无其他文字、数字、官方刊号、表格、水印。', 'negative': '错字，乱码，水印，官方月刊，虚构履历，均匀平铺的文字，表格，标题遮脸，多余人物，面部变形', 'size': '1728x2304', 'final_size': ''},
]


class CardStyleStore:
    """名片生图模板库（JSON 存储，可增删改 ✅）"""

    def __init__(self, data_dir: pathlib.Path | str):
        self.path = pathlib.Path(data_dir) / "card_styles.json"
        self._lock = threading.RLock()
        self._cache: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    def _load(self) -> list[dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, list) and raw:
                    self._cache = raw
                    return self._cache
        except Exception:
            pass
        self._cache = [dict(x) for x in DEFAULT_STYLES]
        self._save()
        return self._cache

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache or [], ensure_ascii=False, indent=2),
                           encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def all(self, *, only_enabled: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rows = [dict(x) for x in self._load()]
        if only_enabled:
            rows = [x for x in rows if x.get("enabled", True)]
        rows.sort(key=lambda x: (int(x.get("order") or 999), str(x.get("key"))))
        return rows

    def get(self, key: str) -> dict[str, Any] | None:
        key = str(key or "").strip()
        for row in self.all():
            if row.get("key") == key or row.get("label") == key:
                return row
        return None

    def add(self, row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        key = str(row.get("key") or "").strip() or f"style{int(time.time())}"
        label = str(row.get("label") or "").strip() or key
        with self._lock:
            rows = self._load()
            if any(x.get("key") == key for x in rows):
                return "exists", {}
            entry = {
                "key": key, "label": label,
                "prompt": str(row.get("prompt") or "").strip(),
                "negative": str(row.get("negative") or "").strip(),
                "size": str(row.get("size") or "").strip(),
                "final_size": str(row.get("final_size") or "").strip(),
                "enabled": bool(row.get("enabled", True)),
                "order": int(row.get("order") or (len(rows) + 1)),
            }
            rows.append(entry)
            self._save()
            return "ok", entry

    def update(self, key: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            for row in self._load():
                if row.get("key") != key:
                    continue
                for f in ("label", "prompt", "negative", "size", "final_size"):
                    if f in patch and patch[f] is not None:
                        row[f] = str(patch[f])
                if "enabled" in patch:
                    row["enabled"] = bool(patch["enabled"])
                if "order" in patch:
                    try: row["order"] = int(patch["order"])
                    except Exception: pass
                self._save()
                return dict(row)
            return None

    def delete(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            rows = self._load()
            for i, row in enumerate(rows):
                if row.get("key") == key:
                    removed = rows.pop(i)
                    self._save()
                    return removed
            return None

    def reset(self) -> int:
        with self._lock:
            self._cache = [dict(x) for x in DEFAULT_STYLES]
            self._save()
            return len(self._cache)

    def menu(self) -> list[tuple[str, str]]:
        """用于菜单选择 ✅"""
        return [(x["key"], x.get("label") or x["key"]) for x in self.all(only_enabled=True)]
