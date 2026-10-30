# Homebrew formula for Paper Cart, written by packaging/homebrew/formula.py.
# Do not edit by hand. The release workflow copies it to the tap as Formula/paper-cart.rb.
class PaperCart < Formula
  desc "Follow journals you choose and keep the papers you mean to read"
  homepage "https://github.com/sunwookwak-polisci/Paper-Cart"
  url "https://github.com/sunwookwak-polisci/Paper-Cart/releases/download/v0.1.0/paper_cart-0.1.0-py3-none-any.whl", using: :nounzip
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"

  depends_on "uv" => :build
  depends_on :macos
  depends_on "python@3.13"

  on_arm do
    resource "markupsafe" do
      url "https://files.pythonhosted.org/packages/9c/d9/5f7756922cdd676869eca1c4e3c0cd0df60ed30199ffd775e319089cb3ed/markupsafe-3.0.3-cp313-cp313-macosx_11_0_arm64.whl", using: :nounzip
      sha256 "116bb52f642a37c115f517494ea5feb03889e04df47eeff5b130b1808ce7c219"
    end

    resource "pydantic-core" do
      url "https://files.pythonhosted.org/packages/21/43/6323b1f8b217780454c61304bcd2b38ae4762f50754414124603ccc90bb2/pydantic_core-2.46.5-cp313-cp313-macosx_11_0_arm64.whl", using: :nounzip
      sha256 "f332f0e72a5a0400141f830744e141bf9f97917878dbe968669e8a7fefea78ff"
    end
  end

  on_intel do
    resource "markupsafe" do
      url "https://files.pythonhosted.org/packages/38/2f/907b9c7bbba283e68f20259574b13d005c121a0fa4c175f9bed27c4597ff/markupsafe-3.0.3-cp313-cp313-macosx_10_13_x86_64.whl", using: :nounzip
      sha256 "e1cf1972137e83c5d4c136c43ced9ac51d0e124706ee1c8aa8532c1287fa8795"
    end

    resource "pydantic-core" do
      url "https://files.pythonhosted.org/packages/f5/37/5abe39a8372a61d3dc3c1338fc504281c01b32fdb3169cd7187153b56d3e/pydantic_core-2.46.5-cp313-cp313-macosx_10_12_x86_64.whl", using: :nounzip
      sha256 "b7ca9034437b6022f941f4857459562ee00a560b97e7cce8a0ec5a74fc6766e0"
    end
  end

  resource "annotated-doc" do
    url "https://files.pythonhosted.org/packages/3e/30/e900b21425a860e195f32e37657aa1f7c7f2b1bfb26f03ca209b90933c06/annotated_doc-0.0.5-py3-none-any.whl", using: :nounzip
    sha256 "117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101"
  end

  resource "annotated-types" do
    url "https://files.pythonhosted.org/packages/99/91/8acff4f5e50511b911bbccb72b8628a49c68ce14148cd9f6431094859a90/annotated_types-0.8.0-py3-none-any.whl", using: :nounzip
    sha256 "f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0"
  end

  resource "anyio" do
    url "https://files.pythonhosted.org/packages/12/b8/4bd346e22b28902df4d651910f5242c28d84e4a5c2435ca5c3f797ed7e2e/anyio-4.15.1-py3-none-any.whl", using: :nounzip
    sha256 "6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101"
  end

  resource "certifi" do
    url "https://files.pythonhosted.org/packages/0b/a7/71ac2cff56fec219ed242bb11b8efb69fcc4bec75db06fb7bfe35de520e6/certifi-2026.7.22-py3-none-any.whl", using: :nounzip
    sha256 "62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775"
  end

  resource "click" do
    url "https://files.pythonhosted.org/packages/58/50/6c0d534c5f134586a8e1ba4e330569e32f057e33372ae556463212fb4cd3/click-8.5.0-py3-none-any.whl", using: :nounzip
    sha256 "255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360"
  end

  resource "fastapi" do
    url "https://files.pythonhosted.org/packages/4d/17/bb503d4b3bea614eae48ffecafe192b097082e8afcf3f2dbde3d78438cc4/fastapi-0.142.1-py3-none-any.whl", using: :nounzip
    sha256 "7eea2b5b1632ed43de2c090b3a43b7d92267189dfbbd55a967307ed763b6c57a"
  end

  resource "h11" do
    url "https://files.pythonhosted.org/packages/04/4b/29cac41a4d98d144bf5f6d33995617b185d14b22401f75ca86f384e87ff1/h11-0.16.0-py3-none-any.whl", using: :nounzip
    sha256 "63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86"
  end

  resource "httpcore" do
    url "https://files.pythonhosted.org/packages/7e/f5/f66802a942d491edb555dd61e3a9961140fd64c90bce1eafd741609d334d/httpcore-1.0.9-py3-none-any.whl", using: :nounzip
    sha256 "2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55"
  end

  resource "httpx" do
    url "https://files.pythonhosted.org/packages/2a/39/e50c7c3a983047577ee07d2a9e53faf5a69493943ec3f6a384bdc792deb2/httpx-0.28.1-py3-none-any.whl", using: :nounzip
    sha256 "d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad"
  end

  resource "idna" do
    url "https://files.pythonhosted.org/packages/58/a2/bb081bab032533a855d44de1d56f8e8426114ff1ba5d1f07a438a0a654f8/idna-3.20-py3-none-any.whl", using: :nounzip
    sha256 "ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c"
  end

  resource "jinja2" do
    url "https://files.pythonhosted.org/packages/62/a1/3d680cbfd5f4b8f15abc1d571870c5fc3e594bb582bc3b64ea099db13e56/jinja2-3.1.6-py3-none-any.whl", using: :nounzip
    sha256 "85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67"
  end

  resource "opentelemetry-api" do
    url "https://files.pythonhosted.org/packages/44/b9/040d1a1c7836922828e6480cd2366bb8fe0ebf75b413d2bb51a9b0e7f78f/opentelemetry_api-1.45.0-py3-none-any.whl", using: :nounzip
    sha256 "80e068aba7cd56c8b58512d6a36f8d25cb1dfaa0c0a4cc1c938ccf9f362d9cb3"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/eb/47/c95ffc2009878c7aac0c5e08528022dcb885933252a88b5f170058014464/pydantic-2.13.5-py3-none-any.whl", using: :nounzip
    sha256 "346a034f080da3755d8e9cb5e00e8b07de1d39e4f6e2c87d8ab7cafa0b269a73"
  end

  resource "python-multipart" do
    url "https://files.pythonhosted.org/packages/e1/04/e8135ebd1ad02c56ec633277529b2602ff99ff634be76cdba5744cf554fd/python_multipart-0.0.32-py3-none-any.whl", using: :nounzip
    sha256 "ff6d3f776f16878c894e52e107296ffc890e913c611b1a4ec6c44e2821fe2e23"
  end

  resource "starlette" do
    url "https://files.pythonhosted.org/packages/4e/d6/1ec1b290f9e0fb067899b61e1d37a30c923068bad260b216dbe37a7d2967/starlette-1.7.0-py3-none-any.whl", using: :nounzip
    sha256 "67f8e99895493dd2911a03f11314af6ceebeae4e704bb9f43dfc6a9db151c93e"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/49/d3/b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/typing_extensions-4.16.0-py3-none-any.whl", using: :nounzip
    sha256 "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8"
  end

  resource "typing-inspection" do
    url "https://files.pythonhosted.org/packages/67/81/4add07e5172b7ac40d8ed5ff580409a7801a4fe26d529bdd915401dabfbe/typing_inspection-0.4.4-py3-none-any.whl", using: :nounzip
    sha256 "65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147"
  end

  resource "uvicorn" do
    url "https://files.pythonhosted.org/packages/38/0c/b54a4fdd7f90a3af8b02ebc9ce6712c2c208b7926a2f7bad95c33ebbe943/uvicorn-0.54.0-py3-none-any.whl", using: :nounzip
    sha256 "505bdb0f318731d45f1f712071fc781a8981f6847a31c902c9f5e652d4f67faf"
  end

  def install
    ENV["UV_CACHE_DIR"] = buildpath/"uv-cache"
    ENV["UV_PYTHON_DOWNLOADS"] = "never"
    resources.each { |r| r.stage(buildpath/"wheels") }
    system "uv", "venv", "--python", formula_opt_bin("python@3.13")/"python3.13", libexec
    system "uv", "pip", "install", "--python", libexec/"bin/python", "--no-index", "--no-deps",
           *Dir[buildpath/"*.whl", buildpath/"wheels/*.whl"]
    bin.install_symlink libexec/"bin/paper-cart"
  end

  def caveats
    <<~EOS
      Start Paper Cart with:
        paper-cart
      Your library starts in:
        ~/Library/Application Support/Paper Cart
      Choose another folder in Settings. Quit and start Paper Cart again to use it.
      Upgrading or uninstalling the formula leaves the library folder alone.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/paper-cart --version")
    system libexec/"bin/python", "-c", "import paper_cart.web"
  end
end
