// OpenCamera.cpp : This file contains the 'main' function. Program execution begins and ends there.
//

#include <iostream>
#include "opencv2/opencv.hpp"  
#pragma comment(linker, "/subsystem:\"windows\" /entry:\"mainCRTStartup\"")

using namespace cv;

int main()
{
  // ������ͷ  
  VideoCapture cap(0);

  Mat frame;

  // �������ͷ�Ƿ��  
  if (!cap.isOpened())
  {
    std::cout << "�޷�������ͷ" << std::endl;
    return -1;
  }

  // ѭ��������Ƶ  
  while (true)
  {
    // ��ȡһ֡ͼ��  
    cap >> frame;

    // ��ʾͼ��  
    imshow("MSCamera", frame);

    // ����ESC����ո���˳�ѭ��  
    int k = waitKey(1);

    if (k == 32 || k == 27)
    {
      break;
    }
  }

  // �ͷ�����ͷ��Դ  
  cap.release();

  // �رմ���  
  destroyAllWindows();

  return 0;
}