"""Clan battles cog"""
import datetime
import logging
import os
import shelve
import sqlite3
from enum import Enum, IntEnum
from typing import Optional, Tuple, Type, TypeVar

import discord
from discord.ext import commands

from pekobot.bot import Pekobot
from pekobot.utils import db, files

logger = logging.getLogger(__name__)

BOSS_DATA_FILE_PATH = os.path.join("data", "boss_data.yaml")

META_FILE_PATH = "clanbattles-meta.db"

CLAN_MEMBER_TABLE = "clan_member"
CREATE_CLAN_MEMBER_TABLE = f"""
CREATE TABLE {CLAN_MEMBER_TABLE}(
    member_id INTEGER PRIMARY KEY,
    member_name TEXT,
    member_nick TEXT
)
"""
GET_ALL_CLAN_MEMBERS = f'''
SELECT member_name, member_nick FROM {CLAN_MEMBER_TABLE};
'''
COUNT_CLAN_MEMBER_BY_ID = f'''
SELECT COUNT(*) FROM {CLAN_MEMBER_TABLE}
WHERE member_id=%d;
'''
ADD_NEW_CLAN_MEMBER = f"""
INSERT INTO {CLAN_MEMBER_TABLE} (member_id, member_name, member_nick)
VALUES (%d, '%s', '%s');
"""
DELETE_MEMBER_FROM_CLAN = f'''
DELETE FROM {CLAN_MEMBER_TABLE}
WHERE member_id=%d;
'''

CLAN_BATTLE_TABLE = "clan_battle"
CREATE_CLAN_BATTLE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {CLAN_BATTLE_TABLE} (
    date TEXT PRIMARY KEY,
    name TEXt
)
"""
CREATE_NEW_CLAN_BATTLE = f"""
INSERT INTO {CLAN_BATTLE_TABLE} (date, name)
VALUES ('%s', '%s');
"""
COUNT_CLAN_BATTLE = f"""
SELECT COUNT(*) from {CLAN_BATTLE_TABLE}
WHERE date='%s';
"""
GET_CLAN_BATTLE_BY_DATE = f"""
SELECT date, name FROM {CLAN_BATTLE_TABLE}
WHERE date='%s'
"""
GET_ALL_CLAN_BATTLES = f"""
SELECT date, name FROM {CLAN_BATTLE_TABLE};
"""
DELETE_CLAN_BATTLE_BY_DATE = f"""
DELETE FROM {CLAN_BATTLE_TABLE}
WHERE date='%s';
"""

CLAN_BATTLE_RUN_TABLE = "clan_battle_run"
CREATE_CLAN_BATTLE_RUN_TABLE = f"""
CREATE TABLE IF NOT EXISTS {CLAN_BATTLE_RUN_TABLE} (
    id INTEGER AUTOINCREMENT PRIMARY KEY,
    battle_date TEXT NOT NULL,
    member_id INTEGER NOT NULL,
    round INTEGER NOT NULL,
    boss INTEGER NOT NULL,
    damage INTEGER NOT NULL,
    timestamp DATETIME NOT NULL,
    type INTEGER NOT NULL,
    FOREIGN KEY (battle_date) REFERENCES {CLAN_BATTLE_TABLE}(date),
    FOREIGN KEY (member_id) REFERENCES {CLAN_MEMBER_TABLE}(member_id)
)
"""

RunType = TypeVar('RunType', bound='Run')


class Run(IntEnum):
    """Enum that represents a run."""
    FULL = 0
    LAST = 1
    LEFTOVER = 2
    LOST = 3
    UNKNOWN = 4

    @classmethod
    def get_type(cls: Type[RunType], run: str) -> RunType:
        """Gets the corresponding run type for a give string."""
        if run == "full":
            return cls.FULL
        if run == "last":
            return cls.LAST
        if run == "leftover":
            return cls.LEFTOVER
        if run == "lost":
            return cls.LOST
        return cls.UNKNOWN


TierType = TypeVar('TierType', bound='Tier')


class Tier(Enum):
    """Enum that represents a tier."""
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def get_tier(cls: Type[TierType], round_: int) -> TierType:
        """Gets the corresponding tier for a given round."""
        if round_ <= 0:
            return cls.UNKNOWN

        if round_ <= 3:
            return cls.A
        if round_ <= 10:
            return cls.B
        if round_ <= 34:
            return cls.C
        return cls.D


class ClanBattles(commands.Cog, name="公会战插件"):
    """The clan battles cog.

    Attributes:
        bot: A Pekobot instance.
        connections: A dict that holds DB connections.
        meta: A file that stores metadata.
        config: A dict that holds the boss data.
    """
    def __init__(self, bot: Pekobot):
        self.bot = bot
        self.connections = dict()
        self.meta = shelve.open(META_FILE_PATH, writeback=True)
        self.config = files.load_yaml_file(BOSS_DATA_FILE_PATH)

    @commands.command(name="create-clan", aliases=("建会", ))
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def create_clan(self, ctx: commands.Context):
        """创建公会。"""

        logger.info("Creating a clan for the guild %s.", ctx.guild)
        guild_id = ctx.guild.id
        conn = self._get_db_connection(guild_id)
        cursor = conn.cursor()

        if not self._clan_exists(conn):
            cursor.execute(CREATE_CLAN_MEMBER_TABLE)
            logger.info("The clan has been created.")
            await ctx.send("建会成功")
        else:
            logger.warning("The clan already exists.")
            await ctx.send("公会已存在")

    @commands.command(name="join-clan", aliases=("入会", ))
    @commands.guild_only()
    async def join_clan(self, ctx: commands.Context):
        """加入公会。"""

        logger.info("%s (%s) is joining the clan.", ctx.author, ctx.guild)
        guild_id = ctx.guild.id
        conn = self._get_db_connection(guild_id)
        cursor = conn.cursor()

        if not self._clan_exists(conn):
            logger.error("The clan has not been created yet.")
            await ctx.send("公会尚未建立")
        else:
            author = ctx.author
            if self._member_exists(conn, author.id):
                logger.warning("%s is already in the clan.", author)
                await ctx.send("你已是公会成员")
                return

            if author.nick:
                nick = author.nick
            else:
                nick = ""

            cursor.execute(ADD_NEW_CLAN_MEMBER % (author.id, author, nick))
            conn.commit()
            logger.info("%s has joined the clan.", author)
            await ctx.send("入会成功")

    @commands.command(name="leave-clan", aliases=("退会", ))
    @commands.guild_only()
    async def leave_clan(self, ctx: commands.Context):
        """退出公会。"""

        logger.info("%s (%s) is leaving the clan.", ctx.author, ctx.guild)
        guild_id = ctx.guild.id
        conn = self._get_db_connection(guild_id)
        cursor = conn.cursor()

        if not self._clan_exists(conn):
            logger.error("The clan %s has not been created yet.", ctx.guild)
            await ctx.send("公会尚未建立")
        else:
            author = ctx.author
            if not self._member_exists(conn, author.id):
                logger.warning("%s is not in the clan yet.", author)
                await ctx.send("你还不是公会成员")
            else:
                cursor.execute(DELETE_MEMBER_FROM_CLAN % author.id)
                conn.commit()
                logger.info("%s has left the clan.", author)
                await ctx.send("退会成功")

    @commands.command(name="list-members", aliases=("查看成员", ))
    @commands.guild_only()
    async def list_members(self, ctx: commands.Context):
        """查看公会成员。"""

        logger.info("%s (%s) is listing all members of the clan.", ctx.author,
                    ctx.guild)
        guild_id = ctx.guild.id
        conn = self._get_db_connection(guild_id)
        cursor = conn.cursor()

        if not self._clan_exists(conn):
            logger.error("The clan %s has not been created yet.", ctx.guild)
            await ctx.send("公会尚未建立")
        else:
            cursor.execute(GET_ALL_CLAN_MEMBERS)
            display_names = []
            for name, nick in cursor.fetchall():
                if not nick:
                    display_names.append(name)
                else:
                    display_names.append(nick)
            if not display_names:
                await ctx.send("暂无成员入会")
                return
            report = "公会成员\n"
            report += "=======\n"
            report += '\n'.join(display_names)
            await ctx.send(report)

    @commands.command(name="start-clan-battle", aliases=("开始会战", ))
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def start_clan_battle(self, ctx: commands.Context, date="", name=""):
        """开始会战"""

        logger.info("%s (%s) is creating a new clan battle.", ctx.author,
                    ctx.guild)
        if not await self._check_date(ctx, date):
            return

        guild_id = ctx.guild.id
        conn = self._get_db_connection(guild_id)
        cursor = conn.cursor()

        cursor.execute(CREATE_CLAN_BATTLE_TABLE)
        cursor.execute(CREATE_CLAN_BATTLE_RUN_TABLE)

        if self._clan_battle_exists(conn, date):
            logger.warning("Clan battle %s already exists.", date)
            await ctx.send("公会战已存在")
            return

        cursor.execute(CREATE_NEW_CLAN_BATTLE % (date, name))
        conn.commit()
        logger.info("The clan battle %s (%s) has been created.", date, name)
        await ctx.send("成功创建公会战")

        # Set this clan battle as the current clan battle.
        self.meta[str(guild_id)] = {
            "current_battle_date": date,
            "current_battle_name": name
        }
        logger.info("Current clan battle has been updated.")
        if name:
            await ctx.send(f"正在进行中的公会战已更新为：{date} ({name})")
        else:
            await ctx.send(f"正在进行中的公会战已更新为：{date}")

    @commands.command(name="current-clan-battle", aliases=("当前会战", ))
    @commands.guild_only()
    async def show_current_clan_battle(self, ctx: commands.Context):
        """显示正在进行中公会战。"""

        logger.info("%s (%s) is requesting the current clan battle.",
                    ctx.author, ctx.guild)
        data = self._get_current_clan_battle(ctx.guild.id)
        if not data:
            logger.warning("Current clan battle does not exists.")
            await ctx.send("目前无进行中的公会战")
        else:
            date, name = data
            if name:
                logger.info("Current clan battle: %s (%s).", date, name)
                await ctx.send(f"当前公会战：{date} ({name})")
            else:
                logger.info("Current clan battle: %s.", date)
                await ctx.send(f"当前公会战：{date}")

    @commands.command(name="list-clan-battles", aliases=("查看会战", ))
    @commands.guild_only()
    async def list_clan_battles(self, ctx: commands.Context):
        """列举已有的公会战。"""

        logger.info("%s (%s) is listing all clan battles.", ctx.author,
                    ctx.guild)
        guild_id = ctx.guild.id
        conn = self._get_db_connection(guild_id)
        cursor = conn.cursor()

        cursor.execute(GET_ALL_CLAN_BATTLES)
        battles = cursor.fetchall()
        if not battles:
            logger.warning("Clan battles not found.")
            await ctx.send("暂无公会战数据")
            return

        report = "所有公会战\n"
        report += "=======\n"
        for date, name in battles:
            if not name:
                report += f"{date}\n"
            else:
                report += f"{date} ({name})\n"
        await ctx.send(report)

    @commands.command(name="delete-clan-battle", aliases=("删除会战", ))
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def delete_clan_battle(self, ctx: commands.Context, date=""):
        """删除公会战数据。"""

        logger.info("%s (%s) is deleting a clan battle.", ctx.author,
                    ctx.guild)
        if not await self._check_date(ctx, date):
            return

        guild_id = ctx.guild.id
        conn = self._get_db_connection(guild_id)
        cursor = conn.cursor()

        logger.info("The clan battle %s will be deleted.", date)
        if not self._clan_battle_exists(conn, date):
            logger.warning("The clan battle %s does not exist.", date)
            await ctx.send("此公会战不存在")
        else:
            cursor.execute(DELETE_CLAN_BATTLE_BY_DATE % date)
            conn.commit()
            logger.info("The clan battle %s has been deleted.", date)
            await ctx.send("公会战已删除")

            guild_id = str(guild_id)
            try:
                curr_date = self.meta[guild_id]["current_battle_date"]
                if curr_date == date:
                    self.meta[guild_id]["current_battle_date"] = ""
                    self.meta[guild_id]["current_battle_name"] = ""
                    logger.info("Current clan battle has been reset.")
                    await ctx.send("正在进行中的会战已被重置")
            except KeyError:
                pass

    @commands.command(name="set-clan-battle", aliases=("设置会战", ))
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def set_clan_battle(self, ctx: commands.Context, date=""):
        """设置正在进行中的公会战。"""

        logger.info("%s (%s) is setting the current clan battle.", ctx.author,
                    ctx.guild)
        if not await self._check_date(ctx, date):
            return

        guild_id = ctx.guild.id
        conn = self._get_db_connection(guild_id)
        cursor = conn.cursor()

        if not self._clan_battle_exists(conn, date):
            logger.warning("The clan battle %s does not exist.", date)
            await ctx.send("此公会战不存在")
        else:
            guild_id = str(guild_id)
            cursor.execute(GET_CLAN_BATTLE_BY_DATE % date)
            _, name = cursor.fetchone()
            self.meta[guild_id] = {
                "current_battle_date": date,
                "current_battle_name": name
            }
            logger.info("The current clan battle has been set to %s.", date)
            await ctx.send(f"正在进行中的会战已设置为：{date}")

    @commands.command(name="report-run", aliases=("出刀", ))
    @commands.guild_only()
    async def report_run(self, ctx: commands.Context, *args):
        """会战出刀。"""

        logger.info("%s (%s) is reporting a run.", ctx.author, ctx.guild)

        guild_id = ctx.guild.id
        conn = self._get_db_connection(guild_id)
        # cursor = conn.cursor()

        if not self._member_exists(conn, ctx.author.id):
            await ctx.send("你还不是公会成员，无法出刀")
        if not args:
            logger.warning("%s (%s) does not provide the details of the run.",
                           ctx.author, ctx.guild)
            await ctx.send("这是啥刀啊？？？")
            return

        # Damage only
        if len(args) == 1:
            damage = args[0]
            if not self._check_damage(damage):
                logger.error("Invalid damage value: %s.", damage)
                await ctx.send("非法伤害数值")

            damage = int(damage)
            _, _, hp = self._get_current_battle_mata(guild_id)
            if damage > hp:
                logger.warning("Overkill (damage: %d, remaining hp: %d).",
                               damage, hp)
                await ctx.send("伤害数值有误，切勿过度击杀!")

    @commands.command(name="export-data", aliases=("导出数据", ))
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def export_data(self, ctx: commands.Context):
        """导出公会战数据。"""

        logger.info("%s (%s) is export data.", ctx.author, ctx.guild)
        id_ = ctx.author.id
        user = self.bot.get_user(id_)

        db_file = self._get_db_file_name(ctx)
        if os.path.exists(db_file):
            await user.send(file=discord.File(db_file))
            logger.info("Data haS been exported.")
        else:
            logger.warning("Data does not exist.")
            await user.send("数据不存在")

    def _get_db_connection(self, guild_id: int) -> sqlite3.Connection:
        """Gets the DB connection for a given guild.

        Args:
            guild_id: The ID of a guild.
        """

        db_file_name = f"clanbattles-{guild_id}.db"
        try:
            conn = self.connections[db_file_name]
            return conn
        except KeyError:
            conn = sqlite3.connect(db_file_name)
            self.connections[db_file_name] = conn
            return conn

    @staticmethod
    def _get_db_file_name(ctx: commands.Context) -> str:
        """Generates the DB file name for a given guild.

        Args:
            ctx: A command context

        Returns:
            A table name.
        """

        guild_id = ctx.guild.id
        return f"clanbattles-{guild_id}.db"

    @staticmethod
    def _clan_exists(conn: sqlite3.Connection) -> bool:
        """Checks if a clan exists.

        Args:
            conn: A DB connection.

        Returns:
            A bool that indicates if the clan exists.
        """

        return db.table_exists(conn, CLAN_MEMBER_TABLE)

    @staticmethod
    def _member_exists(conn: sqlite3.Connection, member_id: int) -> bool:
        """Checks if a member alreay exists in a clan.

        Args:
            conn: A DB connection.
            member_id: The ID of a member.


        Returns:
            A bool that shows if the member already exists.
        """

        cursor = conn.cursor()
        cursor.execute(COUNT_CLAN_MEMBER_BY_ID % member_id)
        if cursor.fetchone()[0] != 0:
            return True
        return False

    @staticmethod
    def _clan_battle_exists(conn: sqlite3.Connection, date: str) -> bool:
        cursor = conn.cursor()
        cursor.execute(COUNT_CLAN_BATTLE % date)
        if cursor.fetchone()[0] != 0:
            return True
        return False

    @staticmethod
    async def _check_date(ctx: commands.Context, date: str) -> bool:
        """Validates a date.

        Args:
            ctx: A command context.
            date: A date in YYYY-MM-DD format.

        Returns:
            A bool that indicates if the date is valid.
        """

        if not date:
            logger.error("Empty date.")
            await ctx.send("请输入公会战日期")
            return False
        try:
            datetime.datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            logger.error("Invalid date: %s", date)
            await ctx.send("请输入合法日期（YYYY-MM-DD）")
            return False
        return True

    @staticmethod
    def _check_damage(damage: str) -> bool:
        """Validates a damage value.

        Args:
            damage: A damage value.

        Returns:
            A bool that indicates if the damage value is valid.
        """

        if not damage.isdigit() or int(damage) < 0:
            return False
        return True

    def _get_current_clan_battle(self,
                                 guild_id: int) -> Optional[Tuple[str, str]]:
        """Gets the current clan battle.

        Args:
            guild_id: ID of a guild

        Returns:
            A tuple that contains the current clan battle's date and name. Or
            None if no clan battle is found.
        """
        guild_id = str(guild_id)
        try:
            date = self.meta[guild_id]["current_battle_date"]
            name = self.meta[guild_id]["current_battle_name"]
            return date, name
        except KeyError:
            return None

    def _get_current_battle_mata(self, guild_id: int) -> Tuple[int, int, int]:
        """Gets the current round for a given guild.

        Args:
            guild_id: ID of a guild.

        Returns:
            A tuple that contains the current round, boss and remaining hp.
        """

        guild_id = str(guild_id)
        try:
            round_ = self.meta[guild_id]["current_round"]
            boss = self.meta[guild_id]["current_boss"]
            hp = self.meta[guild_id]["remaining_hp"]
            return round_, boss, hp
        except KeyError:
            round_ = 1
            boss = 1
            tier = Tier.get_tier(round_)
            hp = self.config["pcr_jp"]["boss_hp"][f"{tier}{round_}"]
            self.meta[guild_id] = {
                "current_round": round_,
                "current_boss": boss,
                "remaining_hp": hp
            }
            return round_, boss, hp


def setup(bot):
    """A helper function used to load the cog."""

    bot.add_cog(ClanBattles(bot))
