# text adventure engine
簡易テキストアドベンチャー型テンプレートエンジン

## シナリオデータ形式
json形式でシナリオを定義できます
```typescript
{
    title:string            // シナリオのタイトル
    description:string      // シナリオの説明
    scenes:{                // シーンの定義(複数可)
        id:number           // シーンID
        text:string         // シーンの文字列
        image?:string       // シーンの画像
        end?:boolean        // エンディングシーンフラグ
        selection:{         // 選択肢の定義(複数可)
            nextId:number   // 次のシーンID
            text:string     // 選択肢の文字列
        }[]
    }[]
}
```
imageを指定する際は`static`フォルダ内に画像ファイルを配置の上、`/static/[path to image]`の形式で指定してください

## 使用方法
```bash
python app.py [path to json] [path to json] ...
```
引数に指定されたjsonファイルを実行時に読み込んでDBに格納します</br>
過去に読み込まれたシナリオと同一のタイトルのjsonファイルが指定された場合はDB内のシナリオを上書きします(該当シナリオのプレイログは削除されます)

起動後は設定されたポートでサーバが起動します

## 設定方法
`.env`ファイルを作成することで各種設定を行えます</br>
指定しない場合は以下の値に自動的に設定されます(`SECRET_KEY`はランダムに生成されます)
```sh:.env
PORT=5000                     # ポート指定
DATABASE=engine.db            # DBのパス
DEBUG=False                    # flaskのdebugモード
SECRET_KEY=your_secret_key    # flaskのsecret key(安全なkeyを生成して指定してください)
```

## 実行ファイル化
```bash
python build.py
```
`PyInstaller`を用いてpythonの実行環境が無い環境でも動作できるよう実行ファイルを作成できます</br>
`dist`下に生成される実行ファイルと同一パスに`templates`フォルダ, `static`フォルダ, `.env`ファイルを配置して実行してください
