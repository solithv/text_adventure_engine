# text adventure engine

簡易テキストアドベンチャー型テンプレートエンジン

## 使用方法

```bash
python app.py [引数]                # ソースコードから実行する場合
text_adventure_engine.exe [引数]    # 実行ファイルで実行する場合
```

起動時に以下のようなログが表示されます</br>
3行目の`http://192.168.10.100:5000`をユーザに通達してください

```bash
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://192.168.10.100:5000
```

### 引数

- シナリオデータ

    シナリオの情報が書かれたjsonファイルを指定してください</br>
    複数指定や指定なしも可能です</br>
    例：`python app.py scenario.json`

    jsonファイルを実行時に読み込んでDBに格納します</br>
    過去に読み込まれたシナリオとタイトルが同一のjsonファイルが指定された場合はDB内のシナリオを上書きします(該当シナリオのプレイログは削除されます)

    > 読み込みが成功したか必ず確認してください</br>
    > 成功した場合は`Imported scenario: シナリオタイトル`等とログが表示されます</br>
    > 失敗した場合は`Import scenario failed: scenario.json`等とログが表示されます

    [シナリオデータの定義についてはこちら](#シナリオデータの定義)

- ユーザ登録用csvファイル (-r または --register)

    ユーザ一括登録に使用するcsvファイルを指定できます</br>
    ヘッダに`username`, `password`を含んだcsvファイルを指定してください</br>
    登録済みのユーザの場合はパスワードが更新されます</br>
    例：`python app.py -r users.csv`

    > 読み込みが成功したか必ず確認してください</br>
    > 成功した場合は`User registration successful.`とログが表示されます</br>
    > 失敗した場合は`User registration failed.`とログが表示されます

    [csvファイルの詳細はこちら](#ユーザ登録用csvファイル)

- データベースファイル名 (-d または --database)

    データベースのファイル名を指定できます</br>
    指定しない場合は`engine.db`を使用します
        (`.env`で設定している場合は設定されたファイル名)</br>
    例：`python app.py -d mydata.db`

- ポート番号 (-p または --port)

    サーバが使用するポート番号を指定できます</br>
    指定しない場合は`5000`を使用します
        (`.env`で設定している場合は設定されたポート番号)</br>
    例：`python app.py -p 8080`

- ユーザ登録画面の有効化 (--registrable)

    本プログラムはデフォルトではクライアントからのユーザ新規登録を受け付けません</br>
    このオプションを指定することでユーザ登録に関する機能を有効化できます</br>
    例：`python app.py --registrable`

例:

```bash
python app.py scenario1.json scenario2.json -d mydata.db -p 8080
text_adventure_engine.exe scenario1.json scenario2.json -d mydata.db -p 8080
```

## シナリオデータの定義

json形式でシナリオを定義できます

```typescript
{
    title:string                    // シナリオのタイトル
    description:string              // シナリオの説明
    scenes:{                        // シーンの定義(複数可)
        id:number                   // シーンID
        text:string                 // シーンの文字列
        image?:string               // シーンの画像
        end?:boolean                // エンディングシーンフラグ
        selection:{                 // 選択肢の定義(複数可)
            nextId:number|number[]  // 次のシーンID
            text:string             // 選択肢の文字列
        }[]
    }[]
}
```

<details>
<summary>JSON ファイルの基本構造</summary>

### ルート要素

- title (文字列):
    シナリオのタイトルを表します</br>
    例として「冒険の旅」や「魔法の森の物語」など、シナリオの名前を指定します

- description (文字列):
    シナリオの概要やあらすじを説明します</br>
    数行程度で、シナリオの内容を紹介する文章を入力してください

- scenes (下記[シーン要素](#シーン要素-scenes-内のオブジェクト)の配列):
    シナリオ内のシーンを定義する配列です</br>
    それぞれのシーンは、物語の特定の場面や出来事を表します

### シーン要素 (scenes 内のオブジェクト)

各シーンは以下の要素を持ちます：

- id (整数):
    シーンごとに設定する識別番号です</br>
    後の選択肢でシーンを指定する際に使われます</br>
    例として、最初のシーンに 1、次のシーンに 2 などの番号を割り当てます</br>
    一番若い番号のシーンが最初のシーンになります

- text (文字列):
    シーンの本文や描写を記述します</br>
    プレイヤーにシーンの内容や雰囲気を伝える文章を入れます

- image (文字列, 任意):
    シーンに対応する画像のファイルパスや URL を指定します</br>
    画像がない場合、この要素は省略可能です</br>
    詳細は[画像の指定方法](#画像の指定方法)を参照してください

- end (boolean, 任意):
    このシーンがエンディングである場合は true にします</br>
    エンディングシーンに到達すると、物語が終了します

- selection (下記[選択肢要素](#選択肢要素-selection-内のオブジェクト)の配列):
    プレイヤーに提示する選択肢のリストです</br>
    それぞれの選択肢は、プレイヤーの行動を選び次のシーンに移るためのものです</br>
    endがtrueでない場合は1つ以上の要素が必要です

### 選択肢要素 (selection 内のオブジェクト)

選択肢には以下の要素が含まれます：

- nextId (整数 または 整数の配列):
    選択肢を選んだ後に移行するシーンの id を指定します</br>
    整数の配列で指定した場合はランダムで選ばれたシーンに進む設定が可能です

- text (文字列):
    選択肢の内容や説明文です</br>
    プレイヤーが次に進むためのアクションを説明します

</details>

### 画像の指定方法

imageを指定する際は`images`フォルダ内に画像ファイルを配置の上、`images`フォルダからのパスを指定してください</br>
フォルダ名は[設定](#設定)で変更できます

```bash
.
└── images
    ├── folder
    │   └── image3.svg
    ├── image1.png
    └── image2.jpg
```

このようなフォルダ構成の場合には以下のように指定してください

- `"image": "image1.png"`
- `"image": "image2.jpg"`
- `"image": "folder/image3.svg"`

## ユーザ登録用csvファイル

一括で複数のユーザを登録したい場合は以下の形式に準ずるcsvファイルを作成して引数`-r`で指定してください

- 1行目はヘッダ行
- `username`列, `password`列を含む(その他の列が含まれている場合は無視されます)
- `username`列のユーザ名、`password`列のパスワードが1対1で対応

例:

```csv
username,password
user1,password1
user2,password2
user3,password3
```

## 設定

`.env`ファイルを作成することで各種設定を行えます(必須ではありません)</br>
引数での指定があった場合は引数での指定が優先されます</br>
設定可能な項目及びそのデフォルト値は以下です(`SECRET_KEY`はランダムに生成されます)

```sh:.env
PORT=5000                   # ポート指定
DATABASE=engine.db          # DBのファイル名
IMAGE_FOLDER=images         # 画像ファイルの配置フォルダ
UPLOAD_FOLDER=temp          # ファイルアップロードに使用する一時フォルダ
MAX_CONTENT_LENGTH=1048576  # アップロード可能なファイルサイズの上限値
DEBUG=False                 # flaskのdebugモード
SECRET_KEY=your_secret_key  # flaskのsecret key(安全なkeyを生成して指定してください)
```

## 実行ファイル化

```bash
python build.py
```

`PyInstaller`を用いてpythonの実行環境が無い環境でも動作できるよう実行ファイルを作成できます</br>
`dist`下に生成される実行ファイルと同一パスに`images`フォルダ, `.env`ファイルを配置して実行してください
