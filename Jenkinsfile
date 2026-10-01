pipeline {

    agent none

    options {
        timeout(time: 90, unit: 'MINUTES')
        disableConcurrentBuilds(abortPrevious: true)
    }

    parameters {
        booleanParam(
            name: 'FORCE_BUILD_ALL',
            defaultValue: false,
            description: '변경 감지와 관계없이 AI 이미지 4개를 모두 빌드한다.'
        )
    }

    environment {

        SERVICE_NAME    = 'ai'
        BUILD_LABEL     = 'python-builder'

        ECR_REPO        = 'moongcheap/ai'
        ECR_REGISTRY    = '840851421204.dkr.ecr.ap-northeast-2.amazonaws.com'
        AWS_REGION      = 'ap-northeast-2'

        GITOPS_REPO_URL = 'https://github.com/V-MoongCheap/MoongCheap-Cloud.git'

        GITOPS_PR_NUMBER     = ''
        GITOPS_PR_URL        = ''
        GITOPS_PR_STATUS     = ''
        GITOPS_BRANCH_STATUS = ''
        GITOPS_PR_CREATED    = 'false'
    }


    stages {

        // ============================================================
        // Build
        // ============================================================

        stage('Build') {

            agent {
                kubernetes {
                    label BUILD_LABEL
                }
            }

            steps {

                checkout scm

                script {

                    // --------------------------------------------------
                    // Environment
                    // --------------------------------------------------

                    if (env.BRANCH_NAME == 'main') {

                        env.ENVIRONMENT = 'prod'
                        env.BASE_BRANCH = 'main'

                    } else if (env.BRANCH_NAME == 'develop') {

                        env.ENVIRONMENT = 'develop'
                        env.BASE_BRANCH = 'develop'

                    } else {

                        error(
                            "지원하지 않는 Branch입니다: ${env.BRANCH_NAME}"
                        )
                    }


                    // --------------------------------------------------
                    // Git Information
                    // --------------------------------------------------

                    env.GIT_SHORT_SHA = sh(
                        script: 'git rev-parse --short=7 HEAD',
                        returnStdout: true
                    ).trim()

                    env.GIT_FULL_SHA = sh(
                        script: 'git rev-parse HEAD',
                        returnStdout: true
                    ).trim()

                    env.GIT_AUTHOR = sh(
                        script: 'git log -1 --pretty=format:%an',
                        returnStdout: true
                    ).trim()

                    env.GIT_COMMIT_URL =
                        "https://github.com/V-MoongCheap/MoongCheap-AI/commit/${env.GIT_FULL_SHA}"


                    // --------------------------------------------------
                    // Image Tags
                    // --------------------------------------------------

                    env.LABELING_TAG =
                        "labeling-${env.ENVIRONMENT}-${env.GIT_SHORT_SHA}"

                    env.AWARDING_TAG =
                        "awarding-${env.ENVIRONMENT}-${env.GIT_SHORT_SHA}"

                    env.DEMAND_CLUSTERING_TAG =
                        "demand-clustering-${env.ENVIRONMENT}-${env.GIT_SHORT_SHA}"

                    env.SELLER_ANALYSIS_TAG =
                        "seller-analysis-${env.ENVIRONMENT}-${env.GIT_SHORT_SHA}"

                    echo """
                    ================================
                    Build Parameter Debug
                    ================================
                    FORCE_BUILD_ALL: ${params.FORCE_BUILD_ALL}
                    FORCE_BUILD_ALL Type: ${params.FORCE_BUILD_ALL?.getClass()?.getName()}
                    ================================
                    """.stripIndent()

                    // --------------------------------------------------
                    // Change Detection
                    // --------------------------------------------------

                    // Build flags 초기화
                    env.BUILD_LABELING = 'false'
                    env.BUILD_AWARDING = 'false'
                    env.BUILD_DEMAND_CLUSTERING = 'false'
                    env.BUILD_SELLER_ANALYSIS = 'false'

                    if (params.FORCE_BUILD_ALL) {

                        echo "[Build Plan] FORCE_BUILD_ALL enabled"

                        env.BUILD_LABELING = 'true'
                        env.BUILD_AWARDING = 'true'
                        env.BUILD_DEMAND_CLUSTERING = 'true'
                        env.BUILD_SELLER_ANALYSIS = 'true'

                    } else {

                        echo "[Build Plan] FORCE_BUILD_ALL disabled - detecting changed files"

                        def compareFrom =
                            env.GIT_PREVIOUS_SUCCESSFUL_COMMIT ?:
                            env.GIT_PREVIOUS_COMMIT

                        def diffCommand = compareFrom
                            ? "git diff --name-only ${compareFrom} HEAD"
                            : "git diff --name-only HEAD^ HEAD"

                        def changedFiles = sh(
                            script: diffCommand,
                            returnStdout: true
                        ).trim()

                        echo """
                        ================================
                        Changed Files
                        ================================
                        ${changedFiles}
                        """.stripIndent()


                        def files = changedFiles
                            ? changedFiles.split('\n') as List
                            : []


                        // --------------------------------------------------
                        // A Labeling
                        // --------------------------------------------------

                        env.BUILD_LABELING = files.any { file ->

                            file.startsWith('src/') ||

                            file.startsWith(
                                'packaging/a-labeling/'
                            ) ||

                            file == 'docker/Dockerfile.a-labeling' ||

                            file ==
                                'docker/Dockerfile.a-labeling.dockerignore' ||

                            file ==
                                'config/model1_aliases_reviewed_v2.json' ||

                            file ==
                                'config/demand_constraint_aliases.json' ||

                            file ==
                                'config/demand_constraint_rules.json' ||

                            file ==
                                'config/facet_taxonomy_v2_2.json'

                        } ? 'true' : 'false'


                        // --------------------------------------------------
                        // Awarding
                        // --------------------------------------------------

                        env.BUILD_AWARDING = files.any { file ->

                            file.startsWith(
                                'scripts/awarding/'
                            ) ||

                            file.startsWith(
                                'tests/seller_matching/'
                            ) ||

                            file ==
                                'docker/Dockerfile.awarding' ||

                            file ==
                                'docker/Dockerfile.awarding.dockerignore' ||

                            file ==
                                'packaging/awarding/requirements.txt' ||

                            file ==
                                'src/moongcheap_ai/__init__.py' ||

                            file ==
                                'src/moongcheap_ai/seller_matching/__init__.py' ||

                            file ==
                                'src/moongcheap_ai/seller_matching/offer_ranking.py' ||

                            file ==
                                'src/moongcheap_ai/seller_matching/awarding_batch.py'

                        } ? 'true' : 'false'


                        // --------------------------------------------------
                        // Demand Clustering
                        // --------------------------------------------------

                        env.BUILD_DEMAND_CLUSTERING =
                            files.any { file ->

                                file.startsWith('src/') ||

                                file.startsWith(
                                    'packaging/demand-clustering/'
                                ) ||

                                file ==
                                    'docker/Dockerfile.demand-clustering' ||

                                file ==
                                    'docker/Dockerfile.demand-clustering.dockerignore' ||

                                file ==
                                    'scripts/deployment/prepare_demand_clustering_assets.py' ||

                                file ==
                                    'config/model1_aliases_reviewed_v2.json' ||

                                file ==
                                    'config/demand_constraint_aliases.json' ||

                                file ==
                                    'config/demand_constraint_rules.json'

                            } ? 'true' : 'false'


                        // --------------------------------------------------
                        // Seller Analysis
                        // --------------------------------------------------

                        env.BUILD_SELLER_ANALYSIS =
                            files.any { file ->

                                file.startsWith('src/') ||

                                file.startsWith('docs/contracts/') ||

                                file.startsWith('tests/seller_analysis/') ||

                                file ==
                                    'docker/Dockerfile.seller-analysis' ||

                                file ==
                                    'docker/Dockerfile.seller-analysis.dockerignore' ||

                                file ==
                                    'requirements-api.txt'

                            } ? 'true' : 'false'
                    }


                    // --------------------------------------------------
                    // Image list
                    // --------------------------------------------------

                    def selectedTags = []

                    if (env.BUILD_LABELING == 'true') {
                        selectedTags << env.LABELING_TAG
                    }

                    if (env.BUILD_AWARDING == 'true') {
                        selectedTags << env.AWARDING_TAG
                    }

                    if (env.BUILD_DEMAND_CLUSTERING == 'true') {
                        selectedTags << env.DEMAND_CLUSTERING_TAG
                    }

                    if (env.BUILD_SELLER_ANALYSIS == 'true') {
                        selectedTags << env.SELLER_ANALYSIS_TAG
                    }

                    env.IMAGE_TAG = selectedTags.isEmpty()
                        ? 'Skipped'
                        : selectedTags.join(', ')


                    echo """
                    ================================
                    AI Image Build Plan
                    ================================

                    Force Build All:
                    ${params.FORCE_BUILD_ALL}

                    Labeling:
                    ${env.BUILD_LABELING}

                    Awarding:
                    ${env.BUILD_AWARDING}

                    Demand Clustering:
                    ${env.BUILD_DEMAND_CLUSTERING}

                    Seller Analysis:
                    ${env.BUILD_SELLER_ANALYSIS}

                    Images:
                    ${env.IMAGE_TAG}
                    """.stripIndent()


                    // --------------------------------------------------
                    // Discord - CI 시작
                    // --------------------------------------------------

                    try {

                        withCredentials([
                            string(
                                credentialsId: 'discord-webhook-ci',
                                variable: 'DISCORD_WEBHOOK'
                            )
                        ]) {

                            discordSend(

                                webhookURL: env.DISCORD_WEBHOOK,

                                title: "🚀 AI CI 시작",

                                description: """
                                **Branch**  ${env.BRANCH_NAME}
                                **Build**   #${env.BUILD_NUMBER}

                                🔗 [Jenkins Build](${env.BUILD_URL})
                                """.stripIndent()
                            )
                        }

                    } catch (Exception e) {

                        echo """
                        Discord CI 시작 알림 전송 실패:
                        ${e.getClass().getSimpleName()}
                        """.stripIndent()
                    }
                }


                stash(
                    name: 'source',
                    includes: '**/*',
                    excludes: '.git/**',
                    useDefaultExcludes: false
                )
            }
        }


        // ============================================================
        // Test
        // ============================================================

        stage('Test') {

            parallel {


                // ------------------------------------------------------
                // A Labeling
                // ------------------------------------------------------

                stage('A Labeling Test') {

                    when {
                        expression {
                            env.BUILD_LABELING == 'true'
                        }
                    }

                    agent {
                        kubernetes {
                            label BUILD_LABEL
                        }
                    }

                    steps {

                        unstash 'source'

                        container('builder') {

                            sh '''
                                set -eu

                                python -m pip install \
                                  --no-cache-dir \
                                  uv==0.10.7

                                uv sync \
                                  --project packaging/a-labeling \
                                  --python 3.13.12 \
                                  --locked \
                                  --extra data \
                                  --extra dev

                                PYTHONPATH=. uv run \
                                  --project packaging/a-labeling \
                                  --python 3.13.12 \
                                  --no-sync \
                                  pytest -q
                            '''
                        }
                    }
                }


                // ------------------------------------------------------
                // Awarding
                // ------------------------------------------------------

                stage('Awarding Test') {

                    when {
                        expression {
                            env.BUILD_AWARDING == 'true'
                        }
                    }

                    agent {
                        kubernetes {
                            label BUILD_LABEL
                        }
                    }

                    steps {

                        unstash 'source'

                        container('builder') {

                            sh '''
                                set -eu

                                python -m pip install \
                                  --no-cache-dir \
                                  -r packaging/awarding/requirements.txt

                                python -m pip install \
                                  --no-cache-dir \
                                  pytest

                                if [ -d tests/seller_matching ]; then

                                    python -m pytest \
                                      tests/seller_matching \
                                      --ignore=tests/seller_matching/test_baseline.py \
                                      -q

                                elif [ -d tests/awarding ]; then

                                    python -m pytest \
                                      tests/awarding \
                                      -q

                                else

                                    echo \
                                      "Awarding 전용 테스트 디렉토리가 없어 테스트를 생략합니다."
                                fi
                            '''
                        }
                    }
                }


                // ------------------------------------------------------
                // Demand Clustering
                // ------------------------------------------------------

                stage('Demand Clustering Test') {

                    when {
                        expression {
                            env.BUILD_DEMAND_CLUSTERING == 'true'
                        }
                    }

                    agent {
                        kubernetes {
                            label BUILD_LABEL
                        }
                    }

                    steps {

                        unstash 'source'

                        container('builder') {

                            sh '''
                                set -eu

                                python -m pip install \
                                  --no-cache-dir \
                                  uv==0.10.7

                                uv sync \
                                  --project packaging/demand-clustering \
                                  --locked \
                                  --extra data \
                                  --extra dev

                                uv run \
                                  --project packaging/demand-clustering \
                                  --no-sync \
                                  pytest \
                                  -c packaging/demand-clustering/pyproject.toml
                            '''
                        }
                    }
                }


                // ------------------------------------------------------
                // Seller Analysis
                // ------------------------------------------------------

                stage('Seller Analysis Test') {

                    when {
                        expression {
                            env.BUILD_SELLER_ANALYSIS == 'true'
                        }
                    }

                    agent {
                        kubernetes {
                            label BUILD_LABEL
                        }
                    }

                    steps {

                        unstash 'source'

                        container('builder') {

                            sh '''
                                set -eu

                                python -m pip install \
                                  --no-cache-dir \
                                  -r requirements-api.txt

                                python -m pip install \
                                  --no-cache-dir \
                                  pytest \
                                  pandas

                                python -m pytest \
                                  tests/seller_analysis \
                                  -q
                            '''
                        }
                    }
                }
            }
        }


        // ============================================================
        // Dependency Scan
        // ============================================================

        stage('Dependency Scan') {

            agent {
                kubernetes {
                    label BUILD_LABEL
                }
            }

            steps {

                unstash 'source'

                container('trivy') {

                    sh '''
                        set -eu

                        trivy fs \
                          --severity HIGH,CRITICAL \
                          --ignorefile .trivyignore.yaml \
                          --exit-code 0 \
                          .
                    '''
                }
            }
        }


        // ============================================================
        // Secret Scan
        // ============================================================

        stage('Secret Scan') {

            agent {
                kubernetes {
                    label BUILD_LABEL
                }
            }

            steps {

                unstash 'source'

                container('gitleaks') {

                    sh '''
                        set -eu

                        gitleaks dir \
                          . \
                          --config .gitleaks.toml \
                          --exit-code 1 \
                          --redact
                    '''
                }
            }
        }


        // ============================================================
        // Build / Scan / Push
        // ============================================================

        stage('Build, Scan & Push Image') {

            parallel {

                stage('A Labeling Image') {

                    when {
                        expression {
                            env.BUILD_LABELING == 'true'
                        }
                    }

                    agent {
                        kubernetes {
                            inheritFrom 'python-builder'
                            yaml """
                            apiVersion: v1
                            kind: Pod
                            spec:
                              containers:
                                - name: security
                                  image: python:3.13.12-slim-trixie
                                  command:
                                    - cat
                                  tty: true
                            """
                        }
                    }

                    steps {

                        unstash 'source'

                        container('kaniko') {
                            sh '''
                                set -eu

                                /kaniko/executor \
                                  --context="$PWD" \
                                  --dockerfile="$PWD/docker/Dockerfile.a-labeling" \
                                  --destination="$ECR_REGISTRY/$ECR_REPO:${LABELING_TAG}" \
                                  --tar-path="$PWD/image.tar" \
                                  --no-push \
                                  --no-push-cache
                            '''
                        }

                        container('security') {
                            sh '''
                                set -eu

                                export DEBIAN_FRONTEND=noninteractive

                                apt-get update -qq
                                apt-get install -y -qq \
                                  --no-install-recommends \
                                  ca-certificates \
                                  curl \
                                  skopeo

                                python -m pip install \
                                  --no-cache-dir \
                                  --quiet \
                                  awscli

                                TRIVY_VERSION=0.74.0

                                curl -fSL \
                                  -o trivy.tar.gz \
                                  "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"

                                tar -xzf trivy.tar.gz trivy
                                chmod +x trivy

                                ./trivy image \
                                  --input image.tar \
                                  --severity HIGH,CRITICAL \
                                  --exit-code 0

                                IMAGE_TAG="${LABELING_TAG}"

                                echo "ECR 이미지 확인: $ECR_REPO:$IMAGE_TAG"

                                IMAGE_COUNT="$(aws ecr batch-get-image \
                                  --region "$AWS_REGION" \
                                  --repository-name "$ECR_REPO" \
                                  --image-ids "imageTag=$IMAGE_TAG" \
                                  --query 'length(images)' \
                                  --output text)"

                                AUTH_DIR="$(mktemp -d)"
                                AUTH_FILE="$AUTH_DIR/auth.json"
                                trap 'rm -rf "$AUTH_DIR"' EXIT

                                aws ecr get-login-password \
                                  --region "$AWS_REGION" | \
                                  skopeo login \
                                    --authfile "$AUTH_FILE" \
                                    --username AWS \
                                    --password-stdin \
                                    "$ECR_REGISTRY"

                                if [ "$IMAGE_COUNT" = '1' ]; then
                                    echo "ECR에 동일한 태그가 존재합니다."
                                    echo "기존 ECR 이미지를 검사합니다."

                                    skopeo copy \
                                      --authfile "$AUTH_FILE" \
                                      "docker://$ECR_REGISTRY/$ECR_REPO:$IMAGE_TAG" \
                                      "docker-archive:$PWD/existing-image.tar"

                                    ./trivy image \
                                      --input existing-image.tar \
                                      --severity HIGH,CRITICAL \
                                      --exit-code 0

                                    echo "기존 ECR 이미지 보안 검사 완료"
                                    echo "Push를 생략하고 GitOps 업데이트로 진행합니다."

                                elif [ "$IMAGE_COUNT" = '0' ]; then
                                    echo "ECR에 동일한 태그가 없습니다."
                                    echo "새로운 이미지를 Push합니다."

                                    skopeo copy \
                                      --authfile "$AUTH_FILE" \
                                      "docker-archive:$PWD/image.tar" \
                                      "docker://$ECR_REGISTRY/$ECR_REPO:$IMAGE_TAG"

                                    echo "ECR Push 완료: $ECR_REPO:$IMAGE_TAG"

                                else
                                    echo "예상하지 못한 ECR 이미지 조회 결과: $IMAGE_COUNT"
                                    exit 1
                                fi
                            '''
                        }
                    }
                }

                stage('Awarding Image') {

                    when {
                        expression {
                            env.BUILD_AWARDING == 'true'
                        }
                    }

                    agent {
                        kubernetes {
                            inheritFrom 'python-builder'
                            yaml """
                            apiVersion: v1
                            kind: Pod
                            spec:
                              containers:
                                - name: security
                                  image: python:3.13.12-slim-trixie
                                  command:
                                    - cat
                                  tty: true
                            """
                        }
                    }

                    steps {

                        unstash 'source'

                        container('kaniko') {
                            sh '''
                                set -eu

                                /kaniko/executor \
                                  --context="$PWD" \
                                  --dockerfile="$PWD/docker/Dockerfile.awarding" \
                                  --destination="$ECR_REGISTRY/$ECR_REPO:${AWARDING_TAG}" \
                                  --tar-path="$PWD/image.tar" \
                                  --no-push \
                                  --no-push-cache
                            '''
                        }

                        container('security') {
                            sh '''
                                set -eu

                                export DEBIAN_FRONTEND=noninteractive

                                apt-get update -qq
                                apt-get install -y -qq \
                                  --no-install-recommends \
                                  ca-certificates \
                                  curl \
                                  skopeo

                                python -m pip install \
                                  --no-cache-dir \
                                  --quiet \
                                  awscli

                                TRIVY_VERSION=0.74.0

                                curl -fSL \
                                  -o trivy.tar.gz \
                                  "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"

                                tar -xzf trivy.tar.gz trivy
                                chmod +x trivy

                                ./trivy image \
                                  --input image.tar \
                                  --severity HIGH,CRITICAL \
                                  --exit-code 0

                                IMAGE_TAG="${AWARDING_TAG}"

                                echo "ECR 이미지 확인: $ECR_REPO:$IMAGE_TAG"

                                IMAGE_COUNT="$(aws ecr batch-get-image \
                                  --region "$AWS_REGION" \
                                  --repository-name "$ECR_REPO" \
                                  --image-ids "imageTag=$IMAGE_TAG" \
                                  --query 'length(images)' \
                                  --output text)"

                                AUTH_DIR="$(mktemp -d)"
                                AUTH_FILE="$AUTH_DIR/auth.json"
                                trap 'rm -rf "$AUTH_DIR"' EXIT

                                aws ecr get-login-password \
                                  --region "$AWS_REGION" | \
                                  skopeo login \
                                    --authfile "$AUTH_FILE" \
                                    --username AWS \
                                    --password-stdin \
                                    "$ECR_REGISTRY"

                                if [ "$IMAGE_COUNT" = '1' ]; then
                                    echo "ECR에 동일한 태그가 존재합니다."
                                    echo "기존 ECR 이미지를 검사합니다."

                                    skopeo copy \
                                      --authfile "$AUTH_FILE" \
                                      "docker://$ECR_REGISTRY/$ECR_REPO:$IMAGE_TAG" \
                                      "docker-archive:$PWD/existing-image.tar"

                                    ./trivy image \
                                      --input existing-image.tar \
                                      --severity HIGH,CRITICAL \
                                      --exit-code 0

                                    echo "기존 ECR 이미지 보안 검사 완료"
                                    echo "Push를 생략하고 GitOps 업데이트로 진행합니다."

                                elif [ "$IMAGE_COUNT" = '0' ]; then
                                    echo "ECR에 동일한 태그가 없습니다."
                                    echo "새로운 이미지를 Push합니다."

                                    skopeo copy \
                                      --authfile "$AUTH_FILE" \
                                      "docker-archive:$PWD/image.tar" \
                                      "docker://$ECR_REGISTRY/$ECR_REPO:$IMAGE_TAG"

                                    echo "ECR Push 완료: $ECR_REPO:$IMAGE_TAG"

                                else
                                    echo "예상하지 못한 ECR 이미지 조회 결과: $IMAGE_COUNT"
                                    exit 1
                                fi
                            '''
                        }
                    }
                }

                stage('Demand Clustering Image') {

                    when {
                        expression {
                            env.BUILD_DEMAND_CLUSTERING == 'true'
                        }
                    }

                    agent {
                        kubernetes {
                            inheritFrom 'python-builder'
                            yaml """
                            apiVersion: v1
                            kind: Pod
                            spec:
                              containers:
                                - name: security
                                  image: python:3.13.12-slim-trixie
                                  command:
                                    - cat
                                  tty: true
                            """
                        }
                    }

                    steps {

                        unstash 'source'

                        container('kaniko') {
                            sh '''
                                set -eu

                                /kaniko/executor \
                                  --context="$PWD" \
                                  --dockerfile="$PWD/docker/Dockerfile.demand-clustering" \
                                  --destination="$ECR_REGISTRY/$ECR_REPO:${DEMAND_CLUSTERING_TAG}" \
                                  --tar-path="$PWD/image.tar" \
                                  --no-push \
                                  --no-push-cache
                            '''
                        }

                        container('security') {
                            sh '''
                                set -eu

                                export DEBIAN_FRONTEND=noninteractive

                                apt-get update -qq
                                apt-get install -y -qq \
                                  --no-install-recommends \
                                  ca-certificates \
                                  curl \
                                  skopeo

                                python -m pip install \
                                  --no-cache-dir \
                                  --quiet \
                                  awscli

                                TRIVY_VERSION=0.74.0

                                curl -fSL \
                                  -o trivy.tar.gz \
                                  "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"

                                tar -xzf trivy.tar.gz trivy
                                chmod +x trivy

                                ./trivy image \
                                  --input image.tar \
                                  --severity HIGH,CRITICAL \
                                  --exit-code 0

                                IMAGE_TAG="${DEMAND_CLUSTERING_TAG}"

                                echo "ECR 이미지 확인: $ECR_REPO:$IMAGE_TAG"

                                IMAGE_COUNT="$(aws ecr batch-get-image \
                                  --region "$AWS_REGION" \
                                  --repository-name "$ECR_REPO" \
                                  --image-ids "imageTag=$IMAGE_TAG" \
                                  --query 'length(images)' \
                                  --output text)"

                                AUTH_DIR="$(mktemp -d)"
                                AUTH_FILE="$AUTH_DIR/auth.json"
                                trap 'rm -rf "$AUTH_DIR"' EXIT

                                aws ecr get-login-password \
                                  --region "$AWS_REGION" | \
                                  skopeo login \
                                    --authfile "$AUTH_FILE" \
                                    --username AWS \
                                    --password-stdin \
                                    "$ECR_REGISTRY"

                                if [ "$IMAGE_COUNT" = '1' ]; then
                                    echo "ECR에 동일한 태그가 존재합니다."
                                    echo "기존 ECR 이미지를 검사합니다."

                                    skopeo copy \
                                      --authfile "$AUTH_FILE" \
                                      "docker://$ECR_REGISTRY/$ECR_REPO:$IMAGE_TAG" \
                                      "docker-archive:$PWD/existing-image.tar"

                                    ./trivy image \
                                      --input existing-image.tar \
                                      --severity HIGH,CRITICAL \
                                      --exit-code 0

                                    echo "기존 ECR 이미지 보안 검사 완료"
                                    echo "Push를 생략하고 GitOps 업데이트로 진행합니다."

                                elif [ "$IMAGE_COUNT" = '0' ]; then
                                    echo "ECR에 동일한 태그가 없습니다."
                                    echo "새로운 이미지를 Push합니다."

                                    skopeo copy \
                                      --authfile "$AUTH_FILE" \
                                      "docker-archive:$PWD/image.tar" \
                                      "docker://$ECR_REGISTRY/$ECR_REPO:$IMAGE_TAG"

                                    echo "ECR Push 완료: $ECR_REPO:$IMAGE_TAG"

                                else
                                    echo "예상하지 못한 ECR 이미지 조회 결과: $IMAGE_COUNT"
                                    exit 1
                                fi
                            '''
                        }
                    }
                }

                stage('Seller Analysis Image') {

                    when {
                        expression {
                            env.BUILD_SELLER_ANALYSIS == 'true'
                        }
                    }

                    agent {
                        kubernetes {
                            inheritFrom 'python-builder'
                            yaml """
                            apiVersion: v1
                            kind: Pod
                            spec:
                              containers:
                                - name: security
                                  image: python:3.13.12-slim-trixie
                                  command:
                                    - cat
                                  tty: true
                            """
                        }
                    }

                    steps {

                        unstash 'source'

                        container('kaniko') {
                            sh '''
                                set -eu

                                /kaniko/executor \
                                  --context="$PWD" \
                                  --dockerfile="$PWD/docker/Dockerfile.seller-analysis" \
                                  --destination="$ECR_REGISTRY/$ECR_REPO:${SELLER_ANALYSIS_TAG}" \
                                  --tar-path="$PWD/image.tar" \
                                  --no-push \
                                  --no-push-cache
                            '''
                        }

                        container('security') {
                            sh '''
                                set -eu

                                export DEBIAN_FRONTEND=noninteractive

                                apt-get update -qq
                                apt-get install -y -qq \
                                  --no-install-recommends \
                                  ca-certificates \
                                  curl \
                                  skopeo

                                python -m pip install \
                                  --no-cache-dir \
                                  --quiet \
                                  awscli

                                TRIVY_VERSION=0.74.0

                                curl -fSL \
                                  -o trivy.tar.gz \
                                  "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz"

                                tar -xzf trivy.tar.gz trivy
                                chmod +x trivy

                                ./trivy image \
                                  --input image.tar \
                                  --severity HIGH,CRITICAL \
                                  --exit-code 0

                                IMAGE_TAG="${SELLER_ANALYSIS_TAG}"

                                echo "ECR 이미지 확인: $ECR_REPO:$IMAGE_TAG"

                                IMAGE_COUNT="$(aws ecr batch-get-image \
                                  --region "$AWS_REGION" \
                                  --repository-name "$ECR_REPO" \
                                  --image-ids "imageTag=$IMAGE_TAG" \
                                  --query 'length(images)' \
                                  --output text)"

                                AUTH_DIR="$(mktemp -d)"
                                AUTH_FILE="$AUTH_DIR/auth.json"
                                trap 'rm -rf "$AUTH_DIR"' EXIT

                                aws ecr get-login-password \
                                  --region "$AWS_REGION" | \
                                  skopeo login \
                                    --authfile "$AUTH_FILE" \
                                    --username AWS \
                                    --password-stdin \
                                    "$ECR_REGISTRY"

                                if [ "$IMAGE_COUNT" = '1' ]; then
                                    echo "ECR에 동일한 태그가 존재합니다."
                                    echo "기존 ECR 이미지를 검사합니다."

                                    skopeo copy \
                                      --authfile "$AUTH_FILE" \
                                      "docker://$ECR_REGISTRY/$ECR_REPO:$IMAGE_TAG" \
                                      "docker-archive:$PWD/existing-image.tar"

                                    ./trivy image \
                                      --input existing-image.tar \
                                      --severity HIGH,CRITICAL \
                                      --exit-code 0

                                    echo "기존 ECR 이미지 보안 검사 완료"
                                    echo "Push를 생략하고 GitOps 업데이트로 진행합니다."

                                elif [ "$IMAGE_COUNT" = '0' ]; then
                                    echo "ECR에 동일한 태그가 없습니다."
                                    echo "새로운 이미지를 Push합니다."

                                    skopeo copy \
                                      --authfile "$AUTH_FILE" \
                                      "docker-archive:$PWD/image.tar" \
                                      "docker://$ECR_REGISTRY/$ECR_REPO:$IMAGE_TAG"

                                    echo "ECR Push 완료: $ECR_REPO:$IMAGE_TAG"

                                else
                                    echo "예상하지 못한 ECR 이미지 조회 결과: $IMAGE_COUNT"
                                    exit 1
                                fi
                            '''
                        }
                    }
                }
            }
        }

        // ============================================================
        // GitOps
        // ============================================================

        stage('Update GitOps Repo (Image Tags)') {

            agent {
                kubernetes {
                    label 'node-builder'
                }
            }

            steps {

                container('builder') {

                    withCredentials([

                        usernamePassword(
                            credentialsId: 'moongcheap-jenkins-ci',
                            usernameVariable: 'GIT_USER',
                            passwordVariable: 'GIT_TOKEN'
                        )
                    ]) {

                        sh '''
                            set +x
                            set -eu

                            rm -f \
                              gitops-pr-number.txt \
                              gitops-pr-url.txt \
                              gitops-pr-status.txt \
                              gitops-branch-status.txt \
                              gitops-pr-created.txt

                            echo "false" \
                              > gitops-pr-created.txt


                            # ========================================
                            # Git Authentication
                            # ========================================

                            ASKPASS="$(pwd)/git-askpass.sh"

                            cat > "$ASKPASS" <<'EOF'
                              #!/bin/sh
                              case "$1" in
                                *Username*)
                                  printf '%s\\n' "$GIT_USER"
                                  ;;
                                *Password*)
                                  printf '%s\\n' "$GIT_TOKEN"
                                  ;;
                              esac
                              EOF

                            chmod 700 "$ASKPASS"

                            export GIT_ASKPASS="$ASKPASS"
                            export GIT_TERMINAL_PROMPT=0


                            # ========================================
                            # Clone GitOps Repository
                            # ========================================

                            BRANCH_NAME="ci/update-ai-${ENVIRONMENT}-${GIT_SHORT_SHA}-${BUILD_NUMBER}"

                            rm -rf gitops-repo

                            git clone \
                              "$GITOPS_REPO_URL" \
                              gitops-repo

                            cd gitops-repo

                            git fetch \
                              origin \
                              "$BASE_BRANCH"

                            git checkout \
                              -b "$BRANCH_NAME" \
                              "origin/$BASE_BRANCH"


                            # ========================================
                            # yq
                            # ========================================

                            YQ_VERSION="v4.44.3"

                            curl -fSL \
                              "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_amd64" \
                              -o yq

                            chmod +x yq


                            # ========================================
                            # AI Image Tag Update
                            # ========================================

                            CHANGED_SERVICES=""


                            update_tag() {

                                SERVICE_FILE="$1"

                                IMAGE_VALUE="$2"

                                OVERRIDE_FILE="gitops/values/overrides/${ENVIRONMENT}/${SERVICE_FILE}.yaml"


                                if [ ! -f "$OVERRIDE_FILE" ]; then

                                    echo \
                                      "GitOps override 없음 - 건너뜀: $OVERRIDE_FILE"

                                    return 0
                                fi


                                IMAGE_TAG="$IMAGE_VALUE" \
                                  ./yq -i \
                                  '.image.tag = strenv(IMAGE_TAG)' \
                                  "$OVERRIDE_FILE"


                                if ! git diff \
                                  --quiet \
                                  -- "$OVERRIDE_FILE"
                                then

                                    CHANGED_SERVICES="${CHANGED_SERVICES} ${SERVICE_FILE}"

                                    echo \
                                      "GitOps tag 변경: ${SERVICE_FILE} -> ${IMAGE_VALUE}"
                                fi
                            }


                            if [ "$BUILD_SELLER_ANALYSIS" = "true" ]; then

                                update_tag \
                                  "ai-seller-analysis" \
                                  "$SELLER_ANALYSIS_TAG"
                            fi


                            if [ "$BUILD_LABELING" = "true" ]; then

                                update_tag \
                                  "ai-labeling" \
                                  "$LABELING_TAG"
                            fi


                            if [ "$BUILD_AWARDING" = "true" ]; then

                                update_tag \
                                  "ai-awarding" \
                                  "$AWARDING_TAG"
                            fi


                            if [ "$BUILD_DEMAND_CLUSTERING" = "true" ]; then

                                update_tag \
                                  "ai-demand-clustering" \
                                  "$DEMAND_CLUSTERING_TAG"
                            fi


                            if [ -z "$CHANGED_SERVICES" ]; then

                                echo \
                                  "GitOps에서 변경할 Image Tag가 없습니다."

                                cd ..

                                rm -f "$ASKPASS"

                                exit 0
                            fi


                            # ========================================
                            # Helm Validation
                            # ========================================

                            HELM_VERSION="v3.17.3"

                            curl -fSL \
                              "https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz" \
                              -o helm.tar.gz

                            tar -xzf \
                              helm.tar.gz \
                              linux-amd64/helm


                            HELM_BIN="$PWD/linux-amd64/helm"

                            CHART_DIR="gitops/charts/moongcheap-service"

                            BASE_VALUES="gitops/values/base.yaml"

                            ENV_VALUES="gitops/values/env/${ENVIRONMENT}.yaml"


                            for SERVICE_FILE in $CHANGED_SERVICES
                            do

                                SERVICE_VALUES="gitops/values/services/${SERVICE_FILE}.yaml"

                                OVERRIDE_FILE="gitops/values/overrides/${ENVIRONMENT}/${SERVICE_FILE}.yaml"


                                "$HELM_BIN" lint \
                                  "$CHART_DIR" \
                                  -f "$BASE_VALUES" \
                                  -f "$ENV_VALUES" \
                                  -f "$SERVICE_VALUES" \
                                  -f "$OVERRIDE_FILE"


                                "$HELM_BIN" template \
                                  "$SERVICE_FILE" \
                                  "$CHART_DIR" \
                                  --namespace "moongcheap-${ENVIRONMENT}" \
                                  -f "$BASE_VALUES" \
                                  -f "$ENV_VALUES" \
                                  -f "$SERVICE_VALUES" \
                                  -f "$OVERRIDE_FILE" \
                                  > /dev/null
                            done


                            echo "Helm 검증 완료"


                            # ========================================
                            # Git Commit
                            # ========================================

                            git config \
                              user.name \
                              "jenkins-ci"

                            git config \
                              user.email \
                              "jenkins-ci@moongcheap.local"


                            git add \
                              gitops/values/overrides/


                            if git diff \
                              --cached \
                              --quiet
                            then

                                echo \
                                  "GitOps 변경사항이 없습니다."

                                cd ..

                                rm -f "$ASKPASS"

                                exit 0
                            fi


                            git commit \
                              -m "ci(gitops): update ai images (${ENVIRONMENT}-${GIT_SHORT_SHA})"


                            git -c credential.helper= push \
                              origin \
                              "$BRANCH_NAME"


                            # ========================================
                            # GitHub Repository
                            # ========================================

                            REPO_HOST="${GITOPS_REPO_URL#https://}"

                            GITOPS_API_REPO="${REPO_HOST#github.com/}"

                            GITOPS_API_REPO="${GITOPS_API_REPO%.git}"


                            # ========================================
                            # Pull Request
                            # ========================================

                            PR_TITLE="ci(gitops): update ai images (${ENVIRONMENT}-${GIT_SHORT_SHA})"


                            PR_JSON="$(printf \
                              '{"title":"%s","head":"%s","base":"%s"}' \
                              "$PR_TITLE" \
                              "$BRANCH_NAME" \
                              "$BASE_BRANCH")"


                            PR_RESPONSE="$(curl \
                              --fail-with-body \
                              -sS \
                              -X POST \
                              -H "Authorization: Bearer ${GIT_TOKEN}" \
                              -H "Accept: application/vnd.github+json" \
                              "https://api.github.com/repos/${GITOPS_API_REPO}/pulls" \
                              -d "$PR_JSON")"


                            PR_NUMBER="$(printf '%s' \
                              "$PR_RESPONSE" |
                              node -pe \
                              'JSON.parse(require("fs").readFileSync(0,"utf8")).number')"


                            PR_NODE_ID="$(printf '%s' \
                              "$PR_RESPONSE" |
                              node -pe \
                              'JSON.parse(require("fs").readFileSync(0,"utf8")).node_id')"


                            PR_URL="$(printf '%s' \
                              "$PR_RESPONSE" |
                              node -pe \
                              'JSON.parse(require("fs").readFileSync(0,"utf8")).html_url')"


                            echo "$PR_NUMBER" \
                              > ../gitops-pr-number.txt

                            echo "$PR_URL" \
                              > ../gitops-pr-url.txt

                            echo "true" \
                              > ../gitops-pr-created.txt


                            # ========================================
                            # Auto Merge
                            # ========================================

                            GRAPHQL_QUERY="$(printf \
                              '{"query":"mutation { enablePullRequestAutoMerge(input: {pullRequestId: \\"%s\\", mergeMethod: SQUASH}) { pullRequest { number autoMergeRequest { enabledAt } } } }"}' \
                              "$PR_NODE_ID")"


                            MERGE_RESPONSE="$(curl \
                              --fail-with-body \
                              -sS \
                              -X POST \
                              -H "Authorization: Bearer ${GIT_TOKEN}" \
                              -H "Content-Type: application/json" \
                              "https://api.github.com/graphql" \
                              -d "$GRAPHQL_QUERY")"


                            GRAPHQL_ERRORS="$(printf '%s' \
                              "$MERGE_RESPONSE" |
                              node -pe \
                              'const x=JSON.parse(require("fs").readFileSync(0,"utf8")); x.errors ? JSON.stringify(x.errors) : ""')"


                            if [ -n "$GRAPHQL_ERRORS" ]; then

                                echo \
                                  "Auto Merge 활성화 실패: $GRAPHQL_ERRORS"

                                exit 1
                            fi


                            # ========================================
                            # Wait for Merge
                            # ========================================

                            MERGED=false


                            for i in $(seq 1 30)
                            do

                                PR_STATE="$(curl \
                                  --fail-with-body \
                                  -sS \
                                  -H "Authorization: Bearer ${GIT_TOKEN}" \
                                  -H "Accept: application/vnd.github+json" \
                                  "https://api.github.com/repos/${GITOPS_API_REPO}/pulls/${PR_NUMBER}" |
                                  node -pe \
                                  'JSON.parse(require("fs").readFileSync(0,"utf8")).merged')"


                                if [ "$PR_STATE" = "true" ]; then

                                    MERGED=true

                                    break
                                fi


                                echo \
                                  "GitOps PR Merge 대기 중... (${i}/30)"

                                sleep 10
                            done


                            # ========================================
                            # Temporary Branch Cleanup
                            # ========================================

                            if [ "$MERGED" = "true" ]; then


                                if git ls-remote \
                                  --exit-code \
                                  --heads \
                                  origin \
                                  "$BRANCH_NAME" \
                                  >/dev/null 2>&1
                                then

                                    git -c credential.helper= push \
                                      origin \
                                      --delete \
                                      "$BRANCH_NAME"

                                    echo \
                                      "GitOps 임시 브랜치 삭제 완료: $BRANCH_NAME"

                                else

                                    echo \
                                      "GitOps 임시 브랜치가 이미 삭제되어 있습니다: $BRANCH_NAME"
                                fi


                                echo "Merged" \
                                  > ../gitops-pr-status.txt

                                echo "Deleted" \
                                  > ../gitops-branch-status.txt


                            else


                                echo "Pending" \
                                  > ../gitops-pr-status.txt

                                echo "Retained" \
                                  > ../gitops-branch-status.txt
                            fi


                            cd ..

                            rm -f "$ASKPASS"
                        '''


                        script {

                            if (
                                fileExists(
                                    'gitops-pr-number.txt'
                                )
                            ) {

                                env.GITOPS_PR_NUMBER =
                                    readFile(
                                        'gitops-pr-number.txt'
                                    ).trim()
                            }


                            if (
                                fileExists(
                                    'gitops-pr-url.txt'
                                )
                            ) {

                                env.GITOPS_PR_URL =
                                    readFile(
                                        'gitops-pr-url.txt'
                                    ).trim()
                            }


                            if (
                                fileExists(
                                    'gitops-pr-status.txt'
                                )
                            ) {

                                env.GITOPS_PR_STATUS =
                                    readFile(
                                        'gitops-pr-status.txt'
                                    ).trim()
                            }


                            if (
                                fileExists(
                                    'gitops-branch-status.txt'
                                )
                            ) {

                                env.GITOPS_BRANCH_STATUS =
                                    readFile(
                                        'gitops-branch-status.txt'
                                    ).trim()
                            }


                            if (
                                fileExists(
                                    'gitops-pr-created.txt'
                                )
                            ) {

                                env.GITOPS_PR_CREATED =
                                    readFile(
                                        'gitops-pr-created.txt'
                                    ).trim()
                            }
                        }
                    }
                }
            }
        }


        // ============================================================
        // Summary
        // ============================================================

        stage('Summary') {

            agent {
                kubernetes {
                    label BUILD_LABEL
                }
            }

            steps {

                script {

                    echo """
                    ================================
                    AI CI Summary
                    ================================

                    Environment:
                    ${env.ENVIRONMENT}

                    Commit:
                    ${env.GIT_SHORT_SHA}

                    Images:
                    ${env.IMAGE_TAG}

                    GitOps PR:
                    ${env.GITOPS_PR_STATUS ?: 'Skipped'}
                    """.stripIndent()
                }
            }
        }
    }


    // ================================================================
    // Result Notification
    // ================================================================

    post {


        // ------------------------------------------------------------
        // SUCCESS
        // ------------------------------------------------------------

        success {

            script {

                def gitopsInfo


                if (
                    env.GITOPS_PR_CREATED == 'true'
                ) {

                    gitopsInfo = """
                    **GitOps PR**    #${env.GITOPS_PR_NUMBER} (${env.GITOPS_PR_STATUS})
                    **Temp Branch**  ${env.GITOPS_BRANCH_STATUS}

                    🔗 [GitOps PR](${env.GITOPS_PR_URL})
                    """

                } else {

                    gitopsInfo = """
                    **GitOps PR**    Skipped
                    """
                }


                try {

                    withCredentials([

                        string(

                            credentialsId: 'discord-webhook-ci',

                            variable: 'DISCORD_WEBHOOK'
                        )
                    ]) {

                        discordSend(

                            webhookURL:
                                env.DISCORD_WEBHOOK,

                            title:
                                "✅ AI CI 성공",

                            description: """
                            **Environment**  ${env.ENVIRONMENT}
                            **Branch**       ${env.BRANCH_NAME}
                            **Triggered**    ${env.GIT_AUTHOR}
                            **Commit**       ${env.GIT_SHORT_SHA}
                            **Image**        ${env.IMAGE_TAG}
                            **Build**        #${env.BUILD_NUMBER}

                            ${gitopsInfo}
                            🔗 [GitHub Commit](${env.GIT_COMMIT_URL})
                            🔗 [Jenkins Build](${env.BUILD_URL})
                            """.stripIndent(),

                            result:
                                'SUCCESS'
                        )
                    }

                } catch (Exception e) {

                    echo """
                    Discord CI 성공 알림 전송 실패:
                    ${e.getClass().getSimpleName()}
                    """.stripIndent()
                }
            }
        }


        // ------------------------------------------------------------
        // FAILURE
        // ------------------------------------------------------------

        failure {

            script {

                try {

                    withCredentials([

                        string(

                            credentialsId: 'discord-webhook-ci',

                            variable: 'DISCORD_WEBHOOK'
                        )
                    ]) {

                        discordSend(

                            webhookURL:
                                env.DISCORD_WEBHOOK,

                            title:
                                "❌ AI CI 실패",

                            description: """
                            **Environment**  ${env.ENVIRONMENT ?: '-'}
                            **Branch**       ${env.BRANCH_NAME ?: '-'}
                            **Triggered**    ${env.GIT_AUTHOR ?: '-'}
                            **Commit**       ${env.GIT_SHORT_SHA ?: '-'}
                            **Build**        #${env.BUILD_NUMBER}

                            🔗 [GitHub Commit](${env.GIT_COMMIT_URL ?: 'https://github.com/V-MoongCheap/MoongCheap-AI'})
                            🔗 [Jenkins Build](${env.BUILD_URL})
                            """.stripIndent(),

                            result:
                                'FAILURE'
                        )
                    }

                } catch (Exception e) {

                    echo """
                    Discord CI 실패 알림 전송 실패:
                    ${e.getClass().getSimpleName()}
                    """.stripIndent()
                }
            }
        }


        // ------------------------------------------------------------
        // ABORTED
        // ------------------------------------------------------------

        aborted {

            script {

                try {

                    withCredentials([

                        string(

                            credentialsId: 'discord-webhook-ci',

                            variable: 'DISCORD_WEBHOOK'
                        )
                    ]) {

                        discordSend(

                            webhookURL:
                                env.DISCORD_WEBHOOK,

                            title:
                                "⚠️ AI CI 중단",

                            description: """
                            **Branch**       ${env.BRANCH_NAME ?: '-'}
                            **Triggered**    ${env.GIT_AUTHOR ?: '-'}
                            **Build**        #${env.BUILD_NUMBER}

                            🔗 [Jenkins Build](${env.BUILD_URL})
                            """.stripIndent(),

                            result:
                                'ABORTED'
                        )
                    }

                } catch (Exception e) {

                    echo """
                    Discord CI 중단 알림 전송 실패:
                    ${e.getClass().getSimpleName()}
                    """.stripIndent()
                }
            }
        }
    }
}
