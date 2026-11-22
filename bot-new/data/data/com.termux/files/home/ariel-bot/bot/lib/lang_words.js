// bot/lib/lang_words.js - word lists for the `.lang` game.
// Each entry is "kana:syllable syllable ...:english meaning". Syllables are Hepburn romaji, one per
// mora (ん is its own "n"; long vowels are separate slots: ho n to u).
const JAPANESE = `
さくら:sa ku ra:cherry blossom
ひかり:hi ka ri:light
ゆめ:yu me:dream
こんばんは:ko n ba n wa:good evening
こんにちは:ko n ni chi wa:hello / good afternoon
おはよう:o ha yo u:good morning
ありがとう:a ri ga to u:thank you
さようなら:sa yo u na ra:goodbye
ねこ:ne ko:cat
いぬ:i nu:dog
さかな:sa ka na:fish
とり:to ri:bird
うさぎ:u sa gi:rabbit
くま:ku ma:bear
つき:tsu ki:moon
ほし:ho shi:star
そら:so ra:sky
うみ:u mi:sea
やま:ya ma:mountain
かわ:ka wa:river
はな:ha na:flower
あめ:a me:rain
ゆき:yu ki:snow
かぜ:ka ze:wind
たいよう:ta i yo u:sun
みず:mi zu:water
おちゃ:o cha:tea
ごはん:go ha n:rice / meal
すし:su shi:sushi
うどん:u do n:udon noodles
そば:so ba:soba noodles
たまご:ta ma go:egg
りんご:ri n go:apple
みかん:mi ka n:mandarin orange
ぶどう:bu do u:grapes
すいか:su i ka:watermelon
ばなな:ba na na:banana
いちご:i chi go:strawberry
さけ:sa ke:salmon / sake
おかし:o ka shi:sweets / snacks
ともだち:to mo da chi:friend
かぞく:ka zo ku:family
せんせい:se n se i:teacher
がくせい:ga ku se i:student
えき:e ki:train station
くるま:ku ru ma:car
でんしゃ:de n sha:train
じてんしゃ:ji te n sha:bicycle
ひこうき:hi ko u ki:airplane
ほん:ho n:book
つくえ:tsu ku e:desk
いす:i su:chair
とけい:to ke i:clock / watch
かさ:ka sa:umbrella
くつ:ku tsu:shoes
ふく:fu ku:clothes
ぼうし:bo u shi:hat
めがね:me ga ne:glasses
かばん:ka ba n:bag
てがみ:te ga mi:letter
でんわ:de n wa:telephone
まど:ma do:window
へや:he ya:room
いえ:i e:house
にわ:ni wa:garden
みせ:mi se:shop
まち:ma chi:town
くに:ku ni:country
しごと:shi go to:work / job
かいしゃ:ka i sha:company
びょういん:byo u i n:hospital
やすみ:ya su mi:rest / holiday
ゆうびん:yu u bi n:mail
うた:u ta:song
おんがく:o n ga ku:music
えいが:e i ga:movie
しゃしん:sha shi n:photograph
ほんとう:ho n to u:true / really
だいじょうぶ:da i jo u bu:okay / all right
おいしい:o i shi i:delicious
かわいい:ka wa i i:cute
たのしい:ta no shi i:fun
うれしい:u re shi i:happy
かなしい:ka na shi i:sad
おおきい:o o ki i:big
ちいさい:chi i sa i:small
あたらしい:a ta ra shi i:new
あつい:a tsu i:hot
さむい:sa mu i:cold
はやい:ha ya i:fast / early
おそい:o so i:slow / late
あした:a shi ta:tomorrow
きのう:ki no u:yesterday
きょう:kyo u:today
いま:i ma:now
あさ:a sa:morning
ひる:hi ru:daytime / noon
よる:yo ru:night
おかあさん:o ka a sa n:mother
おとうさん:o to u sa n:father
おにいさん:o ni i sa n:older brother
おねえさん:o ne e sa n:older sister
いもうと:i mo u to:younger sister
おとうと:o to u to:younger brother
さくらんぼ:sa ku ra n bo:cherry
ひまわり:hi ma wa ri:sunflower
あさがお:a sa ga o:morning glory
とんぼ:to n bo:dragonfly
ちょうちょう:cho u cho u:butterfly
ほたる:ho ta ru:firefly
かえる:ka e ru:frog
へび:he bi:snake
さる:sa ru:monkey
ぞう:zo u:elephant
きりん:ki ri n:giraffe
ひつじ:hi tsu ji:sheep
うま:u ma:horse
ぶた:bu ta:pig
とら:to ra:tiger
りゅう:ryu u:dragon
おに:o ni:ogre / demon
ひとり:hi to ri:one person / alone
ふたり:fu ta ri:two people
みんな:mi n na:everyone
すごい:su go i:amazing
がんばれ:ga n ba re:do your best
やさしい:ya sa shi i:kind / gentle
たからもの:ta ka ra mo no:treasure
`;

function parse(raw) {
    return raw.trim().split('\n').map(line => {
        const [kana, syl, en] = line.trim().split(':');
        const syls = syl.trim().split(/\s+/);
        const roman = syls.join('');
        return { kana, syl: syls, en: en.trim(), display: roman[0].toUpperCase() + roman.slice(1) };
    });
}

export const LANGUAGES = {
    japanese: { name: 'Japanese', words: parse(JAPANESE) },
};
export const LANG_ALIASES = { japanese: 'japanese', jp: 'japanese', ja: 'japanese', jap: 'japanese' };
