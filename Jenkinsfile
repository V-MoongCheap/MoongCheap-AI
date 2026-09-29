// Cloud `gitops/jenkins/pipelines/Jenkinsfile.template` 안내대로 애플리케이션 저장소
// 최상위에 둔 파이프라인이다. 템플릿을 그대로 쓰고 CONFIG 블록과 Build/Test 명령만 채웠다.
//
// ⚠️ 이 파일이 만드는 이미지는 **판매자 수요 분석 내부 API 하나**다.
//    이 저장소에는 파트별로 이미지가 네 개 있다 —
//    docker/Dockerfile.seller-analysis (C) · Dockerfile.awarding (C) ·
//    Dockerfile.a-labeling (A) · Dockerfile.demand-clustering (B).
//    나머지 셋을 어떤 잡으로 돌릴지는 정해지지 않았다.
//    docs/cloud-handoff/README.md 의 확인 요청 1번 참고.

pipeline {
    agent none

    environment {
        SERVICE_NAME    = 'ai'
        BUILD_LABEL     = 'python-builder'          // Jenkins values 의 python:3.11-slim
        ECR_REPO        = 'moongcheap/ai'
        ECR_REGISTRY    = '840851421204.dkr.ecr.ap-northeast-2.amazonaws.com'
        GITOPS_REPO_URL = 'https://github.com/V-MoongCheap/MoongCheap-Cloud.git'
        DOCKERFILE_PATH = 'docker/Dockerfile.seller-analysis'
    }

    stages {
        stage('Build') {
            agent { kubernetes { label BUILD_LABEL } }
            steps {
                checkout scm
                script {
                    if (env.BRANCH_NAME == 'main') {
                        env.ENVIRONMENT = 'prod'
                        env.BASE_BRANCH = 'main'
                    } else if (env.BRANCH_NAME == 'develop') {
                        env.ENVIRONMENT = 'develop'
                        env.BASE_BRANCH = 'develop'
                    } else {
                        error "지원하지 않는 배포 브랜치입니다: ${env.BRANCH_NAME}"
                    }

                    env.GIT_SHORT_SHA = sh(script: 'git rev-parse --short=7 HEAD', returnStdout: true).trim()
                    env.IMAGE_TAG = "${env.ENVIRONMENT}-${env.GIT_SHORT_SHA}"
                }
                container('builder') {
                    // 이미지 런타임은 requirements-api.txt 만 쓴다.
                    // 테스트는 pandas·pytest 가 더 필요해 여기서만 설치한다.
                    sh '''
                        python -m pip install --no-cache-dir -r requirements-api.txt "pytest>=8,<9" "pandas>=2.2,<3"
                    '''
                }
                stash name: 'build-output', includes: '**', excludes: '.git/**'
            }
        }

        stage('Test') {
            agent { kubernetes { label BUILD_LABEL } }
            steps {
                unstash 'build-output'
                container('builder') {
                    sh '''
                        python -m pip install --no-cache-dir -r requirements-api.txt "pytest>=8,<9" "pandas>=2.2,<3"
                        python -m pytest tests/seller_analysis -q
                    '''
                }
            }
        }

        stage('Build & Push Image to ECR') {
            agent { kubernetes { label BUILD_LABEL } }
            steps {
                unstash 'build-output'
                container('kaniko') {
                    sh """
                      /kaniko/executor \
                        --context=`pwd` \
                        --dockerfile=`pwd`/${DOCKERFILE_PATH} \
                        --destination=${ECR_REGISTRY}/${ECR_REPO}:${IMAGE_TAG}
                    """
                }
            }
        }

        // 'Update GitOps Repo (Image Tag)' 단계는 템플릿 원본을 그대로 쓴다.
        // 이 저장소에서 옮겨 적으면 자격증명·PR 생성 부분이 어긋날 수 있어 옮기지 않았다.
    }
}
