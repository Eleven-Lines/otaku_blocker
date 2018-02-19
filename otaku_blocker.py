from local_settings import ck, cs, at, ts
import twitter
import pickle


class OtakuBlocker:
    def __init__(self):
        self._api = twitter.Api(ck, cs, at, ts,
                                sleep_on_rate_limit=True)
        credential = self._api.VerifyCredentials()
        self._user_screen_name = credential.screen_name
        self._user_id = credential.id

    def _generate_slug_and_owner(self, listname):
        if "/" in listname:
            owner, slug = listname.split("/")
            return (owner[1:], slug)
        else:
            return (self._user_screen_name, listname)

    def lists(self, slug=False):
        if slug:
            return [l.slug for l in self._api.GetListsList()]
        return [l.full_name for l in self._api.GetListsList()]

    def list_members(self, listname, prettify=True):
        owner, slug = self._generate_slug_and_owner(listname)
        members = self._api.GetListMembers(slug=slug,
                                           owner_screen_name=owner)
        if not prettify:
            return [l.id for l in members]
        return ["@" + l.screen_name for l in members]

    def fetch_user_timeline(self, screen_name):
        timeline = self._api.GetUserTimeline(screen_name=screen_name,
                                             count=200)
        return [f"{t.id} @{t.user.screen_name} {t.text}" for t in timeline]

    def fetch_replies(self,
                      target_screen_name,
                      targets_listname,
                      count=200,
                      max_id=0,
                      prettify=True):
        if count <= 0:
            return []

        owner, slug = self._generate_slug_and_owner(targets_listname)

        targets_id_list = self.list_members(listname=targets_listname,
                                            prettify=False)
        timeline = self._api.GetUserTimeline(screen_name=target_screen_name,
                                             max_id=max_id,
                                             count=200)
        next_max_id = timeline[-1].id
        if prettify:
            replies = [s.text for s in timeline
                       if s.in_reply_to_user_id in targets_id_list]
        else:
            replies = [s for s in timeline
                       if s.in_reply_to_user_id in targets_id_list]

        next = self.fetch_replies(target_screen_name,
                                  targets_listname,
                                  count-200,
                                  next_max_id,
                                  prettify)

        return replies + next

    def search_tweets(self, query, count,
                      max_id=None, since_id=0, prettify=True):
        if count <= 0:
            return []
        results = self._api.GetSearch(term=query,
                                      max_id=max_id,
                                      since_id=since_id,
                                      count=min(100, count))
        if not results:
            return []
        next_id = results[-1].id-1
        next = self.search_tweets(query, count-100,
                                  next_id, since_id, prettify)

        if prettify:
            return [f"{t.text}" for t in results] + next
        else:
            return results + next

    def run(self, targets_listname,
            use_replies_cache=False,
            use_whitelise_cache=False,
            replies_search_count=500,
            search_count=2000,
            white_list=None,          # list to exclude
            strict=False,             # strict mode: block for all mentions
            exclude_friends=True,     # good choice
            exclude_my_friends=True,  # merciful
            ):
        # fetch targets
        owner, slug = self._generate_slug_and_owner(targets_listname)
        targets = self._api.GetListMembers(slug=slug, owner_screen_name=owner)

        # validate
        if use_replies_cache or use_whitelise_cache:
            try:
                with open(".cache/targets", "rb") as f:
                    if str(pickle.load(f)) != str(targets):
                        raise RuntimeError("Invalid cache file")
            except FileNotFoundError as e:
                use_replies_cache = False
                use_whitelise_cache = False
        with open(".cache/targets", "wb") as f:
            pickle.dump(targets, f)

        # find mentions between targets
        replies = []
        if not use_replies_cache:
            for target in targets:
                replies += self.fetch_replies(target.screen_name,
                                              targets_listname,
                                              count=replies_search_count,
                                              prettify=False)
        else:
            with open(".cache/replies", "rb") as f:
                replies = pickle.load(f)
            print("Loaded replies cache.")
        with open(".cache/replies", "wb") as f:
            pickle.dump(replies, f)

        print(f"Found {len(replies)} replies in target list.")

        # whitelist
        if not use_whitelise_cache:
            whitelist = [u.id for u in targets]
            ids_to_exclude_friends = []
            if exclude_friends:
                ids_to_exclude_friends.extend([u.id for u in targets])
            if exclude_my_friends:
                ids_to_exclude_friends.append(self._user_id)
            for target_id in ids_to_exclude_friends:
                whitelist += self._api.GetFriendIDs(user_id=target_id)
        else:
            with open(".cache/whitelist", "rb") as f:
                whitelist = pickle.load(f)
            print("Loaded whitelist cache.")
        with open(".cache/whitelist", "wb") as f:
            pickle.dump(whitelist, f)

        print(f"Added {len(whitelist)} accounts to whitelist.")

        try:
            with open(".cache/last_tweet_id", "rb") as f:
                since_id = pickle.load(f)
        except IOError as e:
            since_id = 0

        # find tweets we hate
        q = " OR ".join(["to:" + t.screen_name for t in targets])
        search_results = self.search_tweets(q, search_count,
                                            since_id=since_id, prettify=False)
        last_tweet_id = 0
        replies_ids = [t.id for t in replies]
        wastes = set()
        for tweet in search_results:
            if ((strict or tweet.in_reply_to_status_id in replies_ids)
                    and tweet.user.id not in whitelist):
                last_tweet_id = max(last_tweet_id, tweet.id)
                wastes.add(tweet.user.id)

        with open(".cache/last_tweet_id", "wb") as f:
            pickle.dump(last_tweet_id, f)

        print(f"It will block {len(wastes)} users. Proceed?[y/N]")
        if (input().lower() != "y"):
            return

        block_count = 0

        for user in wastes:
            try:
                self._api.CreateBlock(user_id=user)
                block_count += 1
            except twitter.TwitterError as e:
                pass

        return f"Successfully blocked {block_count} users."


if __name__ == '__main__':
    import fire
    fire.Fire(OtakuBlocker)
